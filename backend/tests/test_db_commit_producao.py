"""Teste de integração que prova persistência REAL entre conexões
independentes — cobre o bug crítico em que `app.db.get_db()` nunca
comitava a transação (só fechava a sessão), fazendo com que TODO INSERT/
UPDATE feito por qualquer rota evaporasse assim que a request terminava.

IMPORTANTE — por que este teste é diferente de todos os outros:
Todos os outros testes da suíte usam a fixture `client` de
`tests/conftest.py`, que sobrescreve `app.dependency_overrides[get_db]`
para injetar a MESMA sessão de teste (`db`), presa dentro de uma transação
externa com savepoints que é sempre desfeita (rollback) ao final do teste.
Isso é ótimo para isolamento entre testes, mas tem um efeito colateral:
como o override nunca é a função `get_db()` real de `app/db.py`, qualquer
bug de "esqueci o commit" dentro dela ficaria invisível pra suíte — os
dados "commitados" (na verdade só savepoints) continuam visíveis pras
queries seguintes da MESMA sessão, mascarando a ausência de commit real.

Este teste, portanto, deliberadamente:
1. NÃO usa a fixture `db`/`client` do conftest.
2. Cria seu próprio `AsyncClient` SEM sobrescrever `get_db` — ou seja, a
   rota chamada usa a função `get_db()` real de `app/db.py`, com uma
   sessão própria por request, exatamente como acontece em produção.
3. Depois da chamada HTTP, abre uma sessão TOTALMENTE NOVA e
   INDEPENDENTE (`AsyncSessionLocal()`, mesmo factory usado por
   `get_db()`/produção) para verificar se o dado está realmente lá — se
   `get_db()` não tivesse comitado, essa segunda sessão não veria nada
   (cada sessão asyncpg é sua própria conexão/transação).
4. Limpa o registro criado ao final, já que não há rollback automático
   (não estamos dentro do padrão savepoint-por-teste).
"""
from __future__ import annotations

import uuid

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.db import AsyncSessionLocal, get_db
from app.main import app
from app.models.entities import Cliente


async def test_cadastro_cliente_persiste_de_verdade_apos_a_request():
    """Prova que um INSERT feito via rota HTTP real (passando pela
    `get_db()` real, sem override de teste) é commitado e fica visível
    para uma conexão totalmente nova e independente — comportamento
    esperado em produção, onde cada request usa sua própria sessão.

    Antes do fix em `app/db.py::get_db()` (que só fazia
    `async with AsyncSessionLocal() as session: yield session`, sem
    `await session.commit()`), este teste falhava: o cliente cadastrado
    pela request HTTP não era encontrado pela sessão nova, provando que
    nada persistia de fato.
    """
    email = f"prod-commit-{uuid.uuid4().hex[:8]}@teste.com"

    # 1. Faz a request HTTP real, SEM sobrescrever get_db — usa a app
    #    exatamente como ela roda em produção (uma sessão/conexão nova
    #    por request via get_db() real de app/db.py). Defensivo: garante
    #    que nenhum outro teste deixou um override vazando.
    assert get_db not in app.dependency_overrides

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/auth/cliente/cadastro",
            json={
                "nome": "Cliente Producao Teste",
                "email": email,
                "senha": "senha12345",
                "celular": "65999990000",
            },
        )
    assert resp.status_code == 201, resp.text

    try:
        # 2. Abre uma sessão NOVA e INDEPENDENTE — mesma factory usada
        #    por get_db()/produção, mas outra conexão física, sem
        #    nenhuma relação com a sessão usada pela request acima.
        async with AsyncSessionLocal() as sessao_verificacao:
            cliente = await sessao_verificacao.scalar(
                select(Cliente).where(Cliente.email == email)
            )

        assert cliente is not None, (
            "Cliente cadastrado via API não foi encontrado por uma sessão "
            "nova e independente — indica que get_db() não comitou a "
            "transação (regressão do bug crítico de persistência)."
        )
        assert cliente.nome == "Cliente Producao Teste"
    finally:
        # 3. Limpeza: como este teste não roda dentro do padrão
        #    savepoint-por-teste (rollback automático), precisamos
        #    apagar explicitamente o que foi persistido de verdade.
        async with AsyncSessionLocal() as sessao_limpeza:
            await sessao_limpeza.execute(delete(Cliente).where(Cliente.email == email))
            await sessao_limpeza.commit()

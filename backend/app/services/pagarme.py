"""Cliente Pagar.me — 3 modos de operação (`PAGARME_MODE`): `simulado`,
`sandbox` e `producao`.

Em `simulado`, nenhuma chave de API é necessária: `SimuladoClient` guarda o
estado da "order" no Redis (chave `simulado:order:{id}`, valor = timestamp
Unix de criação) e simula a confirmação do pagamento decorridos
`SIMULADO_PENDENTE_SEGUNDOS` (~5s) — o suficiente para o frontend/QA
observarem uma transição real de `pendente` → `pago` sem depender da API
real do Pagar.me nem de webhooks assinados.

Em `sandbox`/`producao`, `HttpClient` fala com a API REST real do Pagar.me
(`https://api.pagar.me/core/v5`), autenticando via HTTP Basic com a chave
secreta (`sk_...`) como usuário e senha vazia — os dois modos usam
exatamente a mesma implementação, a única diferença é qual chave
(`settings.pagarme_api_key`) está configurada em cada ambiente.

`get_pagarme()` é o ponto de entrada usado pelos consumidores (Task T8:
checkout/webhook; Task T9: assinaturas) — escolhe a implementação com base
em `settings.pagarme_mode`, sem que o chamador precise saber qual é.

Segurança (repo público): `HttpClient` nunca loga o corpo bruto de uma
requisição/resposta com erro sem antes remover campos que possam conter
dados de cartão (`card`, `card_token`, `number`, `cvv`/`cvc` etc.) — ver
`_higienizar_para_log`.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx
import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger("app.pagarme")

PAGARME_BASE_URL = "https://api.pagar.me/core/v5"

# Tempo (segundos) que uma order simulada permanece "pendente" antes de
# `consultar_order` passar a reportá-la como "pago" — dá tempo de sobra
# para o cliente HTTP/QA observar o estado inicial antes da confirmação.
SIMULADO_PENDENTE_SEGUNDOS = 5

# TTL (segundos) da chave de controle de uma order simulada no Redis —
# generoso o bastante para cobrir qualquer teste/QA manual sem acumular
# lixo indefinidamente no Redis.
SIMULADO_ORDER_TTL_SEGUNDOS = 3600

# Chaves cujo valor nunca deve ir para o log, mesmo dentro de um corpo de
# erro do Pagar.me — cobre tanto o payload que enviamos (card_token) quanto
# o formato de objeto `card` que a API pode ecoar de volta.
_CAMPOS_SENSIVEIS = {"card", "card_token", "number", "cvv", "cvc", "holder_document"}


@dataclass
class OrderResult:
    order_id: str
    charge_id: str
    status: str
    pix_qr_code: str | None = None
    pix_copia_cola: str | None = None


@dataclass
class SubResult:
    subscription_id: str
    status: str


class PagarmeError(Exception):
    """Erro de comunicação com a API do Pagar.me (`HttpClient`).

    Levantada para qualquer resposta HTTP >= 400. O corpo da resposta é
    logado (higienizado, sem dados de cartão) antes da exceção ser
    levantada — a mensagem da exceção em si é só um resumo curto, para não
    duplicar dados sensíveis em lugares que capturam `str(exc)`.
    """


class PagarmeClient:
    """Interface comum implementada por `SimuladoClient` e `HttpClient`.

    `cliente` é tratado por duck typing (não importamos `app.models.entities.
    Cliente` aqui, para manter este serviço desacoplado da camada de
    persistência) — espera-se um objeto/namespace com pelo menos os
    atributos `nome`, `email` e opcionalmente `cpf`/`celular`.
    """

    async def criar_order_pix(
        self, cliente: Any, valor_centavos: int, descricao: str
    ) -> OrderResult:
        raise NotImplementedError

    async def criar_order_cartao(
        self, cliente: Any, valor_centavos: int, descricao: str, card_token: str
    ) -> OrderResult:
        raise NotImplementedError

    async def consultar_order(self, order_id: str) -> str:
        """Retorna `'pendente' | 'pago' | 'falhou'`."""
        raise NotImplementedError

    async def estornar_charge(self, charge_id: str) -> bool:
        raise NotImplementedError

    async def criar_subscription(
        self,
        cliente: Any,
        valor_centavos: int,
        dia_cobranca: int,
        metodo: str,
        card_token: str | None = None,
    ) -> SubResult:
        raise NotImplementedError

    async def cancelar_subscription(self, sub_id: str) -> bool:
        raise NotImplementedError


class SimuladoClient(PagarmeClient):
    """Implementação usada quando `PAGARME_MODE=simulado`.

    Não faz nenhuma chamada de rede: usa o Redis (`redis_url`, por padrão
    `settings.redis_url`) só para lembrar *quando* cada order simulada foi
    criada, o que basta para `consultar_order` simular a confirmação
    assíncrona de um pagamento real (PIX/webhook) sem precisar de um worker
    ou de um webhook de verdade.
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url or settings.redis_url

    def _redis(self) -> aioredis.Redis:
        return aioredis.from_url(self._redis_url)

    @staticmethod
    def _chave_order(order_id: str) -> str:
        return f"simulado:order:{order_id}"

    async def _registrar_criacao(self, order_id: str) -> None:
        client = self._redis()
        try:
            await client.set(
                self._chave_order(order_id),
                str(time.time()),
                ex=SIMULADO_ORDER_TTL_SEGUNDOS,
            )
        finally:
            await client.aclose()

    async def criar_order_pix(
        self, cliente: Any, valor_centavos: int, descricao: str
    ) -> OrderResult:
        order_id = f"order_SIM{uuid.uuid4().hex}"
        charge_id = f"ch_SIM{uuid.uuid4().hex}"
        await self._registrar_criacao(order_id)
        return OrderResult(
            order_id=order_id,
            charge_id=charge_id,
            status="pendente",
            pix_qr_code=f"SIMULADO-QR-{order_id}",
            pix_copia_cola=f"SIMULADO-{order_id}",
        )

    async def criar_order_cartao(
        self, cliente: Any, valor_centavos: int, descricao: str, card_token: str
    ) -> OrderResult:
        order_id = f"order_SIM{uuid.uuid4().hex}"
        charge_id = f"ch_SIM{uuid.uuid4().hex}"
        await self._registrar_criacao(order_id)
        return OrderResult(
            order_id=order_id,
            charge_id=charge_id,
            status="pendente",
            pix_qr_code=None,
            pix_copia_cola=None,
        )

    async def consultar_order(self, order_id: str) -> str:
        client = self._redis()
        try:
            valor = await client.get(self._chave_order(order_id))
        finally:
            await client.aclose()
        if valor is None:
            # Order desconhecida (nunca criada ou TTL expirado): não há
            # como confirmar o pagamento, então tratamos como falha em vez
            # de "pendente" para sempre.
            return "falhou"
        criado_em = float(valor)
        if time.time() - criado_em >= SIMULADO_PENDENTE_SEGUNDOS:
            return "pago"
        return "pendente"

    async def estornar_charge(self, charge_id: str) -> bool:
        return True

    async def criar_subscription(
        self,
        cliente: Any,
        valor_centavos: int,
        dia_cobranca: int,
        metodo: str,
        card_token: str | None = None,
    ) -> SubResult:
        sub_id = f"sub_SIM{uuid.uuid4().hex}"
        return SubResult(subscription_id=sub_id, status="ativa")

    async def cancelar_subscription(self, sub_id: str) -> bool:
        return True


def _higienizar_para_log(corpo: Any) -> Any:
    """Remove recursivamente campos que possam conter dados de cartão de um
    corpo de resposta antes de ele ir para o log (repo público)."""
    if isinstance(corpo, dict):
        return {
            chave: ("***" if chave.lower() in _CAMPOS_SENSIVEIS else _higienizar_para_log(valor))
            for chave, valor in corpo.items()
        }
    if isinstance(corpo, list):
        return [_higienizar_para_log(item) for item in corpo]
    return corpo


# Mapa de status do Pagar.me (order/charge) -> vocabulário interno do
# contrato (`'pendente' | 'pago' | 'falhou'`).
_STATUS_PAGARME_PARA_INTERNO = {
    "pending": "pendente",
    "processing": "pendente",
    "paid": "pago",
    "failed": "falhou",
    "canceled": "falhou",
    "chargedback": "falhou",
}

# Mapa de status de SUBSCRIPTION do Pagar.me -> mesmo vocabulário que
# `SimuladoClient.criar_subscription` já usa ("ativa"). Os status de
# subscription da Pagar.me são um vocabulário distinto do de order/charge
# (`active`, `canceled`, `ended`, `future`, ...), então usam seu próprio
# mapa — o objetivo aqui não é bater 1:1 com o enum `AssinaturaStatus` do
# domínio (isso é responsabilidade de quem consome `SubResult.status`, ex.
# `assinaturas.py`), só manter `SimuladoClient` e `HttpClient` consistentes
# entre si.
_STATUS_SUBSCRIPTION_PAGARME_PARA_INTERNO = {
    "active": "ativa",
    "canceled": "cancelada",
    "ended": "cancelada",
    "pending": "pendente",
    "future": "pendente",
}


class HttpClient(PagarmeClient):
    """Implementação usada quando `PAGARME_MODE` é `sandbox` ou `producao`.

    As duas diferem apenas pela chave (`api_key`) configurada em cada
    ambiente — a Pagar.me usa o prefixo da própria chave (`sk_test_...` vs
    `sk_...`) para rotear a chamada para sandbox ou produção, então não há
    nenhuma outra distinção de código entre os dois modos.
    """

    def __init__(self, api_key: str, base_url: str = PAGARME_BASE_URL) -> None:
        self._api_key = api_key
        self._base_url = base_url

    def _auth(self) -> httpx.BasicAuth:
        # Basic auth do Pagar.me v5: chave secreta como usuário, senha vazia.
        return httpx.BasicAuth(self._api_key, "")

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        async with httpx.AsyncClient(
            base_url=self._base_url, auth=self._auth(), timeout=30.0
        ) as client:
            resp = await client.request(method, path, json=json)

        if resp.status_code >= 400:
            self._logar_erro(resp)
            raise PagarmeError(
                f"Pagar.me retornou {resp.status_code} em {method} {path}"
            )
        if not resp.content:
            return {}
        return resp.json()

    def _logar_erro(self, resp: httpx.Response) -> None:
        try:
            corpo = resp.json()
        except ValueError:
            corpo = resp.text
        logger.error(
            "pagarme: erro HTTP %s em %s %s: %s",
            resp.status_code,
            resp.request.method,
            resp.request.url,
            _higienizar_para_log(corpo),
        )

    @staticmethod
    def _customer_payload(cliente: Any) -> dict:
        payload: dict[str, Any] = {
            "name": getattr(cliente, "nome", None),
            "email": getattr(cliente, "email", None),
            "type": "individual",
        }
        cpf = getattr(cliente, "cpf", None)
        if cpf:
            payload["document"] = cpf
            payload["document_type"] = "CPF"
        celular = getattr(cliente, "celular", None)
        if celular:
            payload["phones"] = {
                "mobile_phone": {
                    "country_code": "55",
                    "area_code": celular[:2],
                    "number": celular[2:],
                }
            }
        return payload

    async def criar_order_pix(
        self, cliente: Any, valor_centavos: int, descricao: str
    ) -> OrderResult:
        body = {
            "items": [
                {"amount": valor_centavos, "description": descricao, "quantity": 1}
            ],
            "customer": self._customer_payload(cliente),
            "payments": [
                {"payment_method": "pix", "pix": {"expires_in": 3600}}
            ],
        }
        data = await self._request("POST", "/orders", json=body)
        charge = (data.get("charges") or [{}])[0]
        transacao = charge.get("last_transaction") or {}
        return OrderResult(
            order_id=data.get("id", ""),
            charge_id=charge.get("id", ""),
            status=_STATUS_PAGARME_PARA_INTERNO.get(data.get("status", ""), "pendente"),
            # `qr_code` é a string EMV "copia-e-cola"; a imagem do QR (o que
            # o frontend renderiza num <img src=...>) vem em `qr_code_url` —
            # usar `qr_code` nos dois campos rendia um <img> quebrado assim
            # que `PAGARME_MODE` saísse de `simulado`.
            pix_qr_code=transacao.get("qr_code_url"),
            pix_copia_cola=transacao.get("qr_code"),
        )

    async def criar_order_cartao(
        self, cliente: Any, valor_centavos: int, descricao: str, card_token: str
    ) -> OrderResult:
        body = {
            "items": [
                {"amount": valor_centavos, "description": descricao, "quantity": 1}
            ],
            "customer": self._customer_payload(cliente),
            "payments": [
                {
                    "payment_method": "credit_card",
                    "credit_card": {"card_token": card_token},
                }
            ],
        }
        data = await self._request("POST", "/orders", json=body)
        charge = (data.get("charges") or [{}])[0]
        return OrderResult(
            order_id=data.get("id", ""),
            charge_id=charge.get("id", ""),
            status=_STATUS_PAGARME_PARA_INTERNO.get(data.get("status", ""), "pendente"),
            pix_qr_code=None,
            pix_copia_cola=None,
        )

    async def consultar_order(self, order_id: str) -> str:
        data = await self._request("GET", f"/orders/{order_id}")
        return _STATUS_PAGARME_PARA_INTERNO.get(data.get("status", ""), "falhou")

    async def estornar_charge(self, charge_id: str) -> bool:
        await self._request("POST", f"/charges/{charge_id}/refund")
        return True

    async def criar_subscription(
        self,
        cliente: Any,
        valor_centavos: int,
        dia_cobranca: int,
        metodo: str,
        card_token: str | None = None,
    ) -> SubResult:
        payment_method = "credit_card" if metodo == "cartao" else metodo
        body: dict[str, Any] = {
            "customer": self._customer_payload(cliente),
            "payment_method": payment_method,
            "billing_type": "prepaid",
            "billing_day": dia_cobranca,
            "items": [
                {
                    "description": "Assinatura Arena Cacerense",
                    "quantity": 1,
                    "pricing_scheme": {"price": valor_centavos, "scheme_type": "unit"},
                }
            ],
        }
        if card_token:
            body["card_token"] = card_token
        data = await self._request("POST", "/subscriptions", json=body)
        return SubResult(
            subscription_id=data.get("id", ""),
            status=_STATUS_SUBSCRIPTION_PAGARME_PARA_INTERNO.get(
                data.get("status", ""), "pendente"
            ),
        )

    async def cancelar_subscription(self, sub_id: str) -> bool:
        await self._request("DELETE", f"/subscriptions/{sub_id}")
        return True


def get_pagarme() -> PagarmeClient:
    """Escolhe a implementação de `PagarmeClient` conforme `settings.
    pagarme_mode`. `sandbox` e `producao` usam a mesma classe (`HttpClient`)
    — só a chave de API configurada no ambiente muda."""
    if settings.pagarme_mode == "simulado":
        return SimuladoClient()
    return HttpClient(api_key=settings.pagarme_api_key)

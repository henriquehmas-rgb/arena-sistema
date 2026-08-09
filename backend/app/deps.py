"""Dependências FastAPI compartilhadas entre routers.

Task T3 (Wave 0): só reexporta `get_db` (definido em `app.db`, reusado aqui
em vez de duplicado — os testes em `tests/conftest.py` já fazem
`app.dependency_overrides[get_db]` usando o objeto de `app.db`, então esta
reexportação precisa continuar sendo o mesmo objeto de função).

`get_cliente_atual`, `get_staff_atual` e `require_admin` (autenticação via
JWT) serão implementados na Task T4, que depende do serviço `app/services/auth.py`
ainda não criado.
"""

from app.db import get_db

__all__ = ["get_db"]

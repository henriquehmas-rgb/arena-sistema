import redis.asyncio as aioredis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_db

router = APIRouter()


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict:
    """Healthcheck real: testa conexão com Postgres e Redis (não hardcoded).

    Usado pelo healthcheck do container `api` no docker-compose (Step 6).
    """
    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    redis_ok = False
    client = aioredis.from_url(settings.redis_url)
    try:
        redis_ok = bool(await client.ping())
    except Exception:
        redis_ok = False
    finally:
        await client.aclose()

    status = "ok" if (db_ok and redis_ok) else "degraded"
    return {"status": status, "db": db_ok, "redis": redis_ok}

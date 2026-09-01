import logging

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis


async def save_markdown(doc_id: str, markdown: str) -> None:
    r = await get_redis()
    await r.set(doc_id, markdown, ex=settings.REDIS_TTL)
    logger.info("Markdown salvo no Redis: id=%s ttl=%ds", doc_id, settings.REDIS_TTL)


async def get_markdown(doc_id: str) -> str | None:
    r = await get_redis()
    return await r.get(doc_id)

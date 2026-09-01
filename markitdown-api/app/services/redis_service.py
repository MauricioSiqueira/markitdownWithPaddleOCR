import asyncio
import gzip
import logging

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

_redis: aioredis.Redis | None = None
_redis_lock = asyncio.Lock()


async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        async with _redis_lock:
            if _redis is None:
                # decode_responses=False para suportar bytes comprimidos (gzip)
                _redis = aioredis.from_url(
                    settings.REDIS_URL,
                    decode_responses=False,
                    max_connections=50,
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )
    return _redis


async def save_status(doc_id: str, status: str) -> None:
    r = await get_redis()
    await r.set(f"{doc_id}:status", status.encode(), ex=settings.REDIS_TTL)


async def get_status(doc_id: str) -> str | None:
    r = await get_redis()
    val = await r.get(f"{doc_id}:status")
    return val.decode() if val else None


async def save_markdown(doc_id: str, markdown: str) -> None:
    r = await get_redis()
    compressed = gzip.compress(markdown.encode("utf-8"))
    await r.set(doc_id, compressed, ex=settings.REDIS_TTL)
    logger.info(
        "Markdown salvo no Redis: id=%s original=%dB comprimido=%dB ttl=%ds",
        doc_id, len(markdown), len(compressed), settings.REDIS_TTL,
    )


async def get_markdown(doc_id: str) -> str | None:
    r = await get_redis()
    compressed = await r.get(doc_id)
    if compressed is None:
        return None
    return gzip.decompress(compressed).decode("utf-8")

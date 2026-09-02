import asyncio
import gzip
import json
import logging
from typing import List, Optional

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


async def save_pages(doc_id: str, pages: List) -> None:
    """Persiste a lista de páginas como JSON comprimido."""
    r = await get_redis()
    compressed = gzip.compress(json.dumps(pages, ensure_ascii=False).encode("utf-8"))
    await r.set(f"{doc_id}:pages", compressed, ex=settings.REDIS_TTL)
    logger.info(
        "Páginas salvas no Redis: id=%s páginas=%d comprimido=%dB",
        doc_id, len(pages), len(compressed),
    )


async def get_pages(doc_id: str) -> Optional[List]:
    r = await get_redis()
    compressed = await r.get(f"{doc_id}:pages")
    if compressed is None:
        return None
    return json.loads(gzip.decompress(compressed).decode("utf-8"))

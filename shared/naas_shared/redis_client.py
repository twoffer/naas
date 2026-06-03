import json

import redis.asyncio as aioredis

from naas_shared.config import get_settings
from naas_shared.constants import STREAM_MAXLEN

_redis = None


async def get_redis() -> aioredis.Redis:
    """Return (or lazily create) the shared async Redis client.

    Module-level singleton — avoids creating a new connection on every call.
    """
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = aioredis.from_url(
            f"redis://{settings.redis_host}:{settings.redis_port}",
            decode_responses=True,
        )
    return _redis


async def publish_to_stream(stream: str, data: dict) -> str:
    """XADD to a Redis Stream. Returns the message ID."""
    r = await get_redis()
    msg_id = await r.xadd(stream, {"data": json.dumps(data)}, maxlen=STREAM_MAXLEN)
    return msg_id


async def publish_to_channel(channel: str, data: dict) -> int:
    """PUBLISH to a Redis Pub/Sub channel. Returns subscriber count."""
    r = await get_redis()
    return await r.publish(channel, json.dumps(data))


async def ensure_consumer_group(stream: str, group: str) -> None:
    """Create consumer group if it doesn't exist. Idempotent.

    Swallows the BUSYGROUP error Redis raises when the group already exists,
    so services can call this on every startup without guarding it themselves.
    """
    r = await get_redis()
    try:
        await r.xgroup_create(stream, group, id="0", mkstream=True)
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise

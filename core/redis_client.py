import asyncio
import fnmatch
import json
import logging
import time
import redis.asyncio as redis
from core.config import settings

logger = logging.getLogger(__name__)


class _InMemoryPubSub:
    """Asyncio queue-backed fallback Pub/Sub when Docker Redis is offline."""

    def __init__(self, bus: dict):
        self._bus = bus
        self._channels: list[str] = []
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

    async def subscribe(self, *channels: str):
        for ch in channels:
            if ch not in self._channels:
                self._channels.append(ch)
                self._bus.setdefault(ch, set()).add(self._queue)

    async def listen(self):
        while True:
            item = await self._queue.get()
            yield item


class _RedisShim:
    """
    Transparent async Redis interface backed either by real Docker Redis
    or an in-process memory store so the backend never crashes when Redis is down.
    """

    def __init__(self, manager: "RedisManager"):
        self._mgr = manager

    async def get(self, key: str):
        if self._mgr._live_redis is not None:
            try:
                return await self._mgr._live_redis.get(key)
            except Exception as e:
                logger.debug(f"Redis GET error for {key}, using memory cache: {e}")
        entry = self._mgr._mem_store.get(key)
        if not entry:
            return None
        val, exp = entry
        if exp is not None and time.time() > exp:
            self._mgr._mem_store.pop(key, None)
            return None
        return val

    async def set(self, key: str, value: str, ex: int = None):
        exp = (time.time() + ex) if ex else None
        self._mgr._mem_store[key] = (value, exp)
        if self._mgr._live_redis is not None:
            try:
                return await self._mgr._live_redis.set(key, value, ex=ex)
            except Exception as e:
                logger.debug(f"Redis SET error for {key}: {e}")
        return True

    async def ping(self):
        if self._mgr._live_redis is not None:
            return await self._mgr._live_redis.ping()
        return False

    async def keys(self, pattern: str = "*"):
        if self._mgr._live_redis is not None:
            try:
                return await self._mgr._live_redis.keys(pattern)
            except Exception:
                pass
        return [k for k in list(self._mgr._mem_store.keys()) if fnmatch.fnmatch(k, pattern)]

    async def scan(self, cursor=0, match: str = "*", count: int = 100):
        if self._mgr._live_redis is not None:
            try:
                return await self._mgr._live_redis.scan(cursor, match=match, count=count)
            except Exception:
                pass
        matched = [k for k in list(self._mgr._mem_store.keys()) if fnmatch.fnmatch(k, match)]
        return 0, matched


class RedisManager:
    def __init__(self):
        self.redis_pool = None
        self._live_redis = None
        self._mem_store: dict = {}
        self._mem_pubsub_bus: dict = {}
        self.redis = _RedisShim(self)

    @property
    def is_connected(self) -> bool:
        return self._live_redis is not None

    async def connect(self):
        """Initializes the connection pool to Docker Redis."""
        try:
            self.redis_pool = redis.ConnectionPool(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=1.5,
                socket_timeout=1.5,
            )
            r = redis.Redis(connection_pool=self.redis_pool)
            await r.ping()
            self._live_redis = r
            logger.info("Successfully connected to Docker Redis.")
        except Exception as e:
            self._live_redis = None
            if self.redis_pool:
                try:
                    await self.redis_pool.disconnect()
                except Exception:
                    pass
                self.redis_pool = None
            logger.error(f"Redis connection failed: {e}")
            raise

    async def close(self):
        """Closes the Redis connection pool."""
        self._live_redis = None
        if self.redis_pool:
            await self.redis_pool.disconnect()
            self.redis_pool = None
            logger.info("Redis connection closed.")

    async def set_json(self, key: str, value: dict, expire: int = None):
        """Stores a dictionary as a JSON string in Redis (and memory mirror)."""
        try:
            json_str = json.dumps(value)
            await self.redis.set(key, json_str, ex=expire)
        except Exception as e:
            logger.error(f"Failed to set JSON for key {key}: {e}")

    async def get_json(self, key: str) -> dict:
        """Retrieves and parses a JSON string from Redis (or memory mirror)."""
        try:
            data = await self.redis.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Failed to get JSON for key {key}: {e}")
            return None

    async def publish_message(self, channel: str, message: dict):
        """Publishes a JSON message to Redis Pub/Sub (or in-memory bus if offline)."""
        payload_str = json.dumps(message)
        if self._live_redis is not None:
            try:
                await self._live_redis.publish(channel, payload_str)
                return
            except Exception as e:
                logger.debug(f"Failed to publish to Redis {channel}, falling back to memory bus: {e}")

        subscribers = self._mem_pubsub_bus.get(channel, set())
        for q in list(subscribers):
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                q.put_nowait({"type": "message", "channel": channel, "data": payload_str})
            except asyncio.QueueFull:
                pass

    def get_subscriber(self):
        """Returns a Pub/Sub object for listening to channels."""
        if self._live_redis is not None:
            return self._live_redis.pubsub()
        return _InMemoryPubSub(self._mem_pubsub_bus)


# Global Redis instance
redis_db = RedisManager()

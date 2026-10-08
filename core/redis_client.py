import json
import redis.asyncio as redis
import logging
from core.config import settings

logger = logging.getLogger(__name__)

class RedisManager:
    def __init__(self):
        self.redis_pool = None

    async def connect(self):
        """Initializes the connection pool to Redis."""
        try:
            self.redis_pool = redis.ConnectionPool(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                decode_responses=True
            )
            self.redis = redis.Redis(connection_pool=self.redis_pool)
            # Ping to check connection
            await self.redis.ping()
            logger.info("Successfully connected to Redis.")
        except Exception as e:
            logger.error(f"Redis connection failed: {e}")
            raise

    async def close(self):
        """Closes the Redis connection pool."""
        if self.redis_pool:
            await self.redis_pool.disconnect()
            logger.info("Redis connection closed.")

    async def set_json(self, key: str, value: dict, expire: int = None):
        """Stores a dictionary as a JSON string in Redis."""
        try:
            json_str = json.dumps(value)
            await self.redis.set(key, json_str, ex=expire)
        except Exception as e:
            logger.error(f"Failed to set JSON for key {key}: {e}")

    async def get_json(self, key: str) -> dict:
        """Retrieves and parses a JSON string from Redis."""
        try:
            data = await self.redis.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Failed to get JSON for key {key}: {e}")
            return None
    
    async def publish_message(self, channel: str, message: dict):
        """Publishes a JSON message to a Redis channel (Pub/Sub)."""
        try:
            await self.redis.publish(channel, json.dumps(message))
        except Exception as e:
            logger.error(f"Failed to publish to {channel}: {e}")

    def get_subscriber(self):
        """Returns a pubsub object to listen for messages asynchronously."""
        try:
            return self.redis.pubsub()
        except Exception as e:
            logger.error(f"Failed to create Redis subscriber: {e}")
            return None

# Global instance to be used across modules
redis_db = RedisManager()

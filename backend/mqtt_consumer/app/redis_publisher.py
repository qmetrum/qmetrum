"""Redis publisher for real-time event streaming.

Uses Redis Streams for reliable, ordered event delivery to downstream consumers
(WebSocket service, alert pipeline, etc.).
"""

from typing import Any

import redis.asyncio as aioredis
import structlog
import orjson

logger = structlog.get_logger()

# Redis Stream keys
STREAM_TELEMETRY = "aspis:telemetry"
STREAM_EVENTS = "aspis:events"
STREAM_ALERTS = "aspis:alerts"
STREAM_DLQ = "aspis:dlq"

# Max stream length (auto-trim old entries)
MAX_STREAM_LEN = 10000


class RedisPublisher:
    """Publishes messages to Redis Streams."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis: aioredis.Redis | None = None

    async def connect(self) -> None:
        """Connect to Redis."""
        self._redis = aioredis.from_url(
            self._redis_url,
            decode_responses=True,
            max_connections=20,
        )
        # Test connection
        await self._redis.ping()
        logger.info("Redis connected", url=self._redis_url)

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.aclose()
            logger.info("Redis disconnected")

    async def publish_telemetry(self, device_sn: str, data: dict[str, Any]) -> None:
        """Publish telemetry data to the telemetry stream."""
        if not self._redis:
            return

        try:
            await self._redis.xadd(
                STREAM_TELEMETRY,
                {"device_sn": device_sn, "payload": orjson.dumps(data).decode()},
                maxlen=MAX_STREAM_LEN,
                approximate=True,
            )
        except Exception as e:
            logger.error("Failed to publish telemetry to Redis", error=str(e))

    async def publish_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Publish an event to the events stream."""
        if not self._redis:
            return

        try:
            await self._redis.xadd(
                STREAM_EVENTS,
                {"event_type": event_type, "payload": orjson.dumps(data).decode()},
                maxlen=MAX_STREAM_LEN,
                approximate=True,
            )
        except Exception as e:
            logger.error("Failed to publish event to Redis", error=str(e))

    async def publish_alert(self, alert_data: dict[str, Any]) -> None:
        """Publish an alert to the alerts stream."""
        if not self._redis:
            return

        try:
            await self._redis.xadd(
                STREAM_ALERTS,
                {"payload": orjson.dumps(alert_data).decode()},
                maxlen=MAX_STREAM_LEN,
                approximate=True,
            )
        except Exception as e:
            logger.error("Failed to publish alert to Redis", error=str(e))

    async def publish_to_dlq(
        self, topic: str, payload: str, error: str
    ) -> None:
        """Publish a failed message to the dead-letter queue."""
        if not self._redis:
            return

        try:
            await self._redis.xadd(
                STREAM_DLQ,
                {
                    "original_topic": topic,
                    "payload": payload,
                    "error": error,
                },
                maxlen=MAX_STREAM_LEN,
                approximate=True,
            )
        except Exception as e:
            logger.error("Failed to publish to DLQ", error=str(e))

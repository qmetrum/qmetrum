"""ASPIS MQTT Consumer -- bridges DJI Cloud API MQTT to application layer.

Subscribes to DJI Cloud API MQTT topics, parses messages, writes to
PostgreSQL, and publishes to Redis Streams for downstream consumers.
"""

import asyncio
import signal
from typing import Any

import orjson
import paho.mqtt.client as mqtt
import structlog

from backend.common.config.settings import get_settings
from backend.common.db.session import async_session
from backend.mqtt_consumer.app.dji_topics import (
    DJITopicType,
    REQUESTS_REPLY_TOPIC,
    SUBSCRIBE_TOPICS,
    TOPIC_PREFIX,
    parse_topic,
    parse_osd_payload,
    parse_state_payload,
    parse_event_payload,
    parse_request_payload,
)
from backend.mqtt_consumer.app.handlers import MessageHandler
from backend.mqtt_consumer.app.redis_publisher import RedisPublisher

settings = get_settings()
logger = structlog.get_logger()


class MQTTConsumer:
    """MQTT consumer that bridges DJI Cloud API to the ASPIS backend."""

    def __init__(self) -> None:
        self._client: mqtt.Client | None = None
        self._redis = RedisPublisher(settings.redis_url)
        self._handler = MessageHandler(self._redis)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = True
        self._message_count = 0
        self._error_count = 0

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        flags: Any,
        rc: int,
        properties: Any = None,
    ) -> None:
        """Callback when connected to MQTT broker."""
        if rc == 0:
            logger.info(
                "Connected to MQTT broker",
                host=settings.mqtt_broker_host,
                client_id=settings.mqtt_client_id,
            )
            for topic in SUBSCRIBE_TOPICS:
                client.subscribe(topic, qos=1)
                logger.info("Subscribed to topic", topic=topic)
        else:
            logger.error("MQTT connection failed", rc=rc)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        rc: int,
        properties: Any = None,
    ) -> None:
        """Callback when disconnected from MQTT broker."""
        if rc != 0:
            logger.warning("Unexpected MQTT disconnect, will reconnect", rc=rc)
        else:
            logger.info("MQTT disconnected cleanly")

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        msg: mqtt.MQTTMessage,
    ) -> None:
        """Callback for incoming MQTT messages -- dispatch to async handler."""
        if self._loop and self._running:
            asyncio.run_coroutine_threadsafe(
                self._process_message(msg.topic, msg.payload),
                self._loop,
            )

    async def _process_message(self, topic: str, payload_bytes: bytes) -> None:
        """Parse and route an incoming MQTT message."""
        self._message_count += 1

        parsed_topic = parse_topic(topic)
        if parsed_topic is None:
            logger.warning("Unrecognized MQTT topic", topic=topic)
            return

        try:
            payload: dict[str, Any] = orjson.loads(payload_bytes)
        except (orjson.JSONDecodeError, ValueError) as e:
            logger.error("Invalid JSON payload", topic=topic, error=str(e))
            await self._redis.publish_to_dlq(
                topic, payload_bytes.decode("utf-8", errors="replace"), str(e)
            )
            self._error_count += 1
            return

        try:
            async with async_session() as session:
                match parsed_topic.topic_type:
                    case DJITopicType.OSD:
                        telemetry = parse_osd_payload(parsed_topic.device_sn, payload)
                        await self._handler.handle_osd(session, telemetry)

                    case DJITopicType.STATE:
                        state = parse_state_payload(parsed_topic.device_sn, payload)
                        await self._handler.handle_state(session, state)

                    case DJITopicType.EVENTS:
                        event = parse_event_payload(parsed_topic.device_sn, payload)
                        await self._handler.handle_event(session, event)

                    case DJITopicType.SERVICES_REPLY:
                        await self._handler.handle_services_reply(
                            session, parsed_topic.device_sn, payload
                        )

                    case DJITopicType.REQUESTS:
                        request = parse_request_payload(parsed_topic.device_sn, payload)
                        reply = await self._handler.handle_request(session, request)
                        if reply and self._client:
                            # Publish reply on requests_reply topic
                            reply_topic = REQUESTS_REPLY_TOPIC.format(
                                gateway_sn=parsed_topic.device_sn
                            )
                            self._client.publish(
                                reply_topic,
                                orjson.dumps(reply),
                                qos=1,
                            )
                            logger.info(
                                "Published request reply",
                                gateway_sn=parsed_topic.device_sn,
                                method=request.method,
                                reply_topic=reply_topic,
                            )

                    case DJITopicType.PROPERTY_SET_REPLY:
                        logger.debug(
                            "Property set reply",
                            device_sn=parsed_topic.device_sn,
                        )

        except Exception as e:
            logger.error(
                "Error processing message",
                topic=topic,
                device_sn=parsed_topic.device_sn,
                error=str(e),
                exc_info=True,
            )
            await self._redis.publish_to_dlq(
                topic, orjson.dumps(payload).decode(), str(e)
            )
            self._error_count += 1

        if self._message_count % 100 == 0:
            logger.info(
                "Consumer stats",
                messages_processed=self._message_count,
                errors=self._error_count,
            )

    async def start(self) -> None:
        """Start the MQTT consumer."""
        self._loop = asyncio.get_event_loop()

        await self._redis.connect()

        self._client = mqtt.Client(
            client_id=settings.mqtt_client_id,
            protocol=mqtt.MQTTv311,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        if settings.mqtt_username:
            self._client.username_pw_set(settings.mqtt_username, settings.mqtt_password)

        if settings.mqtt_use_tls:
            self._client.tls_set()

        self._client.reconnect_delay_set(min_delay=1, max_delay=60)

        port = settings.mqtt_broker_port_tls if settings.mqtt_use_tls else settings.mqtt_broker_port
        logger.info(
            "Connecting to MQTT broker",
            host=settings.mqtt_broker_host,
            port=port,
            tls=settings.mqtt_use_tls,
        )

        try:
            self._client.connect_async(settings.mqtt_broker_host, port)
            self._client.loop_start()
        except Exception as e:
            logger.error("Failed to connect to MQTT broker", error=str(e))
            raise

        logger.info("MQTT Consumer running, waiting for messages...")
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        """Stop the MQTT consumer gracefully."""
        logger.info(
            "Shutting down MQTT Consumer",
            messages_processed=self._message_count,
            errors=self._error_count,
        )
        self._running = False

        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

        await self._redis.disconnect()
        logger.info("MQTT Consumer stopped")


async def run() -> None:
    """Run the MQTT consumer with graceful shutdown."""
    consumer = MQTTConsumer()

    loop = asyncio.get_event_loop()

    def signal_handler() -> None:
        logger.info("Received shutdown signal")
        asyncio.ensure_future(consumer.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await consumer.start()
    except KeyboardInterrupt:
        pass
    finally:
        await consumer.stop()


def main() -> None:
    """Entry point."""
    logger.info("Starting ASPIS MQTT Consumer")
    asyncio.run(run())


if __name__ == "__main__":
    main()

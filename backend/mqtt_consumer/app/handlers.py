"""Message handlers for each DJI Cloud API topic type.

Each handler processes a parsed message and:
1. Writes to PostgreSQL (telemetry, device state, events)
2. Publishes to Redis Streams for downstream consumers (WebSocket, alerts)
"""

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.app.models.models import (
    Dock, DockStatus, Drone, DroneStatus, Telemetry,
)
from backend.mqtt_consumer.app.dji_topics import (
    DeviceEvent, DeviceRequest, DeviceState, DJITopicType, OSDTelemetry,
    build_request_reply,
)
from backend.mqtt_consumer.app.redis_publisher import RedisPublisher

logger = structlog.get_logger()


class MessageHandler:
    """Processes parsed DJI messages and persists them."""

    def __init__(self, redis: RedisPublisher) -> None:
        self.redis = redis

    async def handle_osd(self, session: AsyncSession, telemetry: OSDTelemetry) -> None:
        """Handle OSD telemetry -- write to DB and publish to Redis."""
        logger.debug(
            "Processing OSD telemetry",
            device_sn=telemetry.device_sn,
            lat=telemetry.latitude,
            lng=telemetry.longitude,
            battery=telemetry.battery_percent,
        )

        # Find the drone by serial number
        result = await session.execute(
            select(Drone).where(Drone.serial_number == telemetry.device_sn)
        )
        drone = result.scalar_one_or_none()

        if drone is None:
            # Might be a dock serial number -- check docks
            dock_result = await session.execute(
                select(Dock).where(Dock.serial_number == telemetry.device_sn)
            )
            dock = dock_result.scalar_one_or_none()
            if dock:
                # Update dock heartbeat
                await session.execute(
                    update(Dock)
                    .where(Dock.id == dock.id)
                    .values(
                        last_heartbeat=datetime.now(timezone.utc),
                        status=DockStatus.online,
                    )
                )
                await session.commit()

                # Publish dock telemetry to Redis
                await self.redis.publish_telemetry(
                    device_sn=telemetry.device_sn,
                    data={
                        "type": "dock",
                        "device_sn": telemetry.device_sn,
                        "latitude": telemetry.latitude,
                        "longitude": telemetry.longitude,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
                return

            logger.warning(
                "Unknown device, skipping telemetry",
                device_sn=telemetry.device_sn,
            )
            return

        # Write telemetry record
        telem_record = Telemetry(
            drone_id=drone.id,
            timestamp=datetime.now(timezone.utc),
            latitude=telemetry.latitude,
            longitude=telemetry.longitude,
            altitude=telemetry.altitude,
            speed=telemetry.speed,
            battery_pct=telemetry.battery_percent,
            signal_strength=telemetry.signal_quality,
            heading=telemetry.heading,
            vertical_speed=telemetry.vertical_speed,
            flight_mode=telemetry.flight_mode,
        )
        session.add(telem_record)

        # Update drone status based on telemetry
        new_status = DroneStatus.flying if telemetry.speed > 0.5 else DroneStatus.idle
        await session.execute(
            update(Drone)
            .where(Drone.id == drone.id)
            .values(status=new_status)
        )

        await session.commit()

        # Publish to Redis for real-time consumers
        await self.redis.publish_telemetry(
            device_sn=telemetry.device_sn,
            data={
                "type": "drone",
                "device_sn": telemetry.device_sn,
                "drone_id": drone.id,
                "latitude": telemetry.latitude,
                "longitude": telemetry.longitude,
                "altitude": telemetry.altitude,
                "speed": telemetry.speed,
                "battery_percent": telemetry.battery_percent,
                "heading": telemetry.heading,
                "flight_mode": telemetry.flight_mode,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def handle_state(self, session: AsyncSession, state: DeviceState) -> None:
        """Handle device state change -- update DB and publish to Redis."""
        logger.info(
            "Device state change",
            device_sn=state.device_sn,
            online=state.online,
            firmware=state.firmware_version,
        )

        new_status = DockStatus.online if state.online else DockStatus.offline

        # Try dock first
        result = await session.execute(
            select(Dock).where(Dock.serial_number == state.device_sn)
        )
        dock = result.scalar_one_or_none()

        if dock:
            update_values: dict[str, Any] = {
                "status": new_status,
                "last_heartbeat": datetime.now(timezone.utc),
            }
            if state.firmware_version:
                update_values["firmware_version"] = state.firmware_version

            await session.execute(
                update(Dock).where(Dock.id == dock.id).values(**update_values)
            )
            await session.commit()

            await self.redis.publish_event(
                event_type="device_state",
                data={
                    "device_sn": state.device_sn,
                    "device_type": "dock",
                    "online": state.online,
                    "status": new_status.value,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            return

        # Try drone
        drone_result = await session.execute(
            select(Drone).where(Drone.serial_number == state.device_sn)
        )
        drone = drone_result.scalar_one_or_none()

        if drone:
            drone_status = DroneStatus.idle if state.online else DroneStatus.offline
            await session.execute(
                update(Drone).where(Drone.id == drone.id).values(status=drone_status)
            )
            await session.commit()

            await self.redis.publish_event(
                event_type="device_state",
                data={
                    "device_sn": state.device_sn,
                    "device_type": "drone",
                    "online": state.online,
                    "status": drone_status.value,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
            return

        logger.warning("State change for unknown device", device_sn=state.device_sn)

    async def handle_event(self, session: AsyncSession, event: DeviceEvent) -> None:
        """Handle async event (mission complete, media available, etc.)."""
        logger.info(
            "Device event received",
            device_sn=event.device_sn,
            event_type=event.event_type,
        )

        # Publish all events to Redis -- downstream consumers decide what to do
        await self.redis.publish_event(
            event_type=event.event_type,
            data={
                "device_sn": event.device_sn,
                "event_type": event.event_type,
                "event_data": event.event_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def handle_services_reply(
        self, session: AsyncSession, device_sn: str, payload: dict[str, Any]
    ) -> None:
        """Handle command execution result."""
        data = payload.get("data", payload)
        result_code = data.get("result", data.get("code", -1))

        logger.info(
            "Services reply",
            device_sn=device_sn,
            result_code=result_code,
            method=payload.get("method", "unknown"),
        )

        await self.redis.publish_event(
            event_type="services_reply",
            data={
                "device_sn": device_sn,
                "method": payload.get("method", "unknown"),
                "result_code": result_code,
                "data": data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def handle_request(
        self, session: AsyncSession, request: DeviceRequest
    ) -> dict[str, Any] | None:
        """Handle a device request and return a reply payload.

        Device requests include: config, airport_bind_status, airport_organization_get,
        flighttask_resource_get, etc. The cloud must reply with matching tid/bid.

        Returns a reply payload dict to publish on requests_reply topic,
        or None if no reply is needed.
        """
        logger.info(
            "Device request received",
            gateway_sn=request.gateway_sn,
            method=request.method,
            tid=request.tid,
        )

        # Publish to Redis for monitoring/logging
        await self.redis.publish_event(
            event_type="device_request",
            data={
                "gateway_sn": request.gateway_sn,
                "method": request.method,
                "tid": request.tid,
                "request_data": request.request_data,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Handle known request methods
        match request.method:
            case "config":
                # Dock requests configuration parameters (MQTT, NTP, etc.)
                return build_request_reply(
                    tid=request.tid,
                    bid=request.bid,
                    method=request.method,
                    result=0,
                    output={
                        "ntp_server_host": "pool.ntp.org",
                        "app_id": "aspis-smoke",
                        "app_key": "",
                        "app_license": "",
                    },
                )

            case "airport_bind_status":
                # Dock asks if it is bound to an organization
                return build_request_reply(
                    tid=request.tid,
                    bid=request.bid,
                    method=request.method,
                    result=0,
                    output={
                        "is_device_bind_organization": True,
                        "organization_id": "ids-aspis",
                        "organization_name": "IDS - Industrial Drone Services",
                    },
                )

            case "airport_organization_get":
                # Dock requests organization info
                return build_request_reply(
                    tid=request.tid,
                    bid=request.bid,
                    method=request.method,
                    result=0,
                    output={
                        "organization_name": "IDS - Industrial Drone Services",
                    },
                )

            case "flighttask_resource_get":
                # Dock requests wayline file for a mission
                logger.info(
                    "Dock requesting flight task resource",
                    gateway_sn=request.gateway_sn,
                    data=request.request_data,
                )
                # TODO: look up wayline file URL from database and return it
                return build_request_reply(
                    tid=request.tid,
                    bid=request.bid,
                    method=request.method,
                    result=0,
                    output={
                        "file": {
                            "url": "",
                            "fingerprint": "",
                        },
                    },
                )

            case _:
                logger.warning(
                    "Unhandled device request method",
                    method=request.method,
                    gateway_sn=request.gateway_sn,
                )
                # Reply with success to avoid blocking the device
                return build_request_reply(
                    tid=request.tid,
                    bid=request.bid,
                    method=request.method,
                    result=0,
                )

"""DJI Cloud API MQTT topic definitions and payload parsers.

DJI Cloud API uses structured MQTT topics with JSON payloads.
Reference: https://developer.dji.com/doc/cloud-api-tutorial/en/
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DJITopicType(str, Enum):
    """DJI Cloud API MQTT topic categories.

    Note on serial numbers in topics:
    - OSD uses {device_sn} -- both dock and drone report their own telemetry
    - All other topics use {gateway_sn} -- Dock 3 is the gateway device
    """
    OSD = "osd"                    # Real-time telemetry at 0.5Hz (uses device_sn)
    STATE = "state"                # Device state changes (uses gateway_sn)
    SERVICES_REPLY = "services_reply"  # Command execution results (uses gateway_sn)
    EVENTS = "events"              # Async events: mission complete, media available (uses gateway_sn)
    REQUESTS = "requests"          # Device requests TO cloud: config, bind, file resources (uses gateway_sn)
    PROPERTY_SET_REPLY = "property/set_reply"  # Property update confirmations (uses gateway_sn)


# Topic patterns: thing/product/{gateway_sn or device_sn}/{topic_type}
TOPIC_PREFIX = "thing/product"

# Subscribe to all device topics (+ is MQTT single-level wildcard)
SUBSCRIBE_TOPICS = [
    f"{TOPIC_PREFIX}/+/osd",                # Telemetry from both dock and drone (device_sn)
    f"{TOPIC_PREFIX}/+/state",              # State changes (gateway_sn)
    f"{TOPIC_PREFIX}/+/services_reply",     # Command results (gateway_sn)
    f"{TOPIC_PREFIX}/+/events",             # Async events (gateway_sn)
    f"{TOPIC_PREFIX}/+/requests",           # Device requests to cloud (gateway_sn)
    f"{TOPIC_PREFIX}/+/property/set_reply", # Property confirmations (gateway_sn)
]

# Topic for publishing replies to device requests
# Format: thing/product/{gateway_sn}/requests_reply
REQUESTS_REPLY_TOPIC = f"{TOPIC_PREFIX}/{{gateway_sn}}/requests_reply"


@dataclass
class ParsedTopic:
    """Parsed MQTT topic components."""
    device_sn: str
    topic_type: DJITopicType
    raw_topic: str


def parse_topic(topic: str) -> ParsedTopic | None:
    """Parse a DJI Cloud API MQTT topic string.

    Expected format: thing/product/{device_sn}/{topic_type}

    Returns None if the topic doesn't match the expected pattern.
    """
    parts = topic.split("/")
    if len(parts) < 4 or parts[0] != "thing" or parts[1] != "product":
        return None

    device_sn = parts[2]

    # Handle nested topic types like "property/set_reply"
    topic_suffix = "/".join(parts[3:])

    try:
        topic_type = DJITopicType(topic_suffix)
    except ValueError:
        return None

    return ParsedTopic(
        device_sn=device_sn,
        topic_type=topic_type,
        raw_topic=topic,
    )


@dataclass
class OSDTelemetry:
    """Parsed OSD (telemetry) payload from Dock 3 / Matrice 4TD."""
    device_sn: str
    latitude: float
    longitude: float
    altitude: float
    speed: float
    battery_percent: float
    signal_quality: float
    heading: float
    vertical_speed: float
    flight_mode: str
    raw: dict[str, Any]


def parse_osd_payload(device_sn: str, payload: dict[str, Any]) -> OSDTelemetry:
    """Parse OSD telemetry payload from DJI Cloud API.

    The actual DJI payload structure nests data under 'data' key
    with subkeys like 'latitude', 'longitude', 'height', etc.
    This parser handles both the real DJI format and a simplified test format.
    """
    data = payload.get("data", payload)

    # DJI nests drone telemetry under various keys depending on device type
    # For Dock 3 gateway, drone data may be under a sub-device key
    drone_data = data

    # Check if this is a gateway (Dock) message with sub-device data
    if "sub_devices" in data:
        sub_devices = data.get("sub_devices", [])
        if sub_devices:
            drone_data = sub_devices[0].get("data", {})

    return OSDTelemetry(
        device_sn=device_sn,
        latitude=float(drone_data.get("latitude", 0.0)),
        longitude=float(drone_data.get("longitude", 0.0)),
        altitude=float(drone_data.get("height", drone_data.get("altitude", 0.0))),
        speed=float(drone_data.get("horizontal_speed", drone_data.get("speed", 0.0))),
        battery_percent=float(drone_data.get("battery", {}).get("capacity_percent",
                              drone_data.get("battery_percent", 0.0))),
        signal_quality=float(drone_data.get("wireless_link", {}).get("quality",
                             drone_data.get("signal_quality", 0.0))),
        heading=float(drone_data.get("attitude_head", drone_data.get("heading", 0.0))),
        vertical_speed=float(drone_data.get("vertical_speed", 0.0)),
        flight_mode=str(drone_data.get("mode_code", drone_data.get("flight_mode", "unknown"))),
        raw=payload,
    )


@dataclass
class DeviceState:
    """Parsed device state change."""
    device_sn: str
    online: bool
    firmware_version: str
    device_model: str
    raw: dict[str, Any]


def parse_state_payload(device_sn: str, payload: dict[str, Any]) -> DeviceState:
    """Parse device state payload."""
    data = payload.get("data", payload)
    return DeviceState(
        device_sn=device_sn,
        online=bool(data.get("online", False)),
        firmware_version=str(data.get("firmware_version", "")),
        device_model=str(data.get("device_model", "")),
        raw=payload,
    )


@dataclass
class DeviceEvent:
    """Parsed async event (mission complete, media available, etc.)."""
    device_sn: str
    event_type: str
    event_data: dict[str, Any]
    raw: dict[str, Any]


def parse_event_payload(device_sn: str, payload: dict[str, Any]) -> DeviceEvent:
    """Parse async event payload."""
    data = payload.get("data", payload)
    return DeviceEvent(
        device_sn=device_sn,
        event_type=str(payload.get("method", data.get("event_type", "unknown"))),
        event_data=data,
        raw=payload,
    )


@dataclass
class DeviceRequest:
    """Parsed device request to cloud (config, bind, file resources, etc.).

    The cloud server must reply on thing/product/{gateway_sn}/requests_reply
    with matching tid/bid for the device to process the response.
    """
    gateway_sn: str
    tid: str       # Transaction ID -- must be echoed in reply
    bid: str       # Business ID -- must be echoed in reply
    method: str    # Request method (e.g., config, airport_bind_status, flighttask_resource_get)
    request_data: dict[str, Any]
    raw: dict[str, Any]


def parse_request_payload(gateway_sn: str, payload: dict[str, Any]) -> DeviceRequest:
    """Parse a device request payload."""
    return DeviceRequest(
        gateway_sn=gateway_sn,
        tid=str(payload.get("tid", "")),
        bid=str(payload.get("bid", "")),
        method=str(payload.get("method", "unknown")),
        request_data=payload.get("data", {}),
        raw=payload,
    )


def build_request_reply(
    tid: str,
    bid: str,
    method: str,
    result: int = 0,
    output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a reply payload for a device request.

    Args:
        tid: Transaction ID from the original request (must match).
        bid: Business ID from the original request (must match).
        method: Method from the original request.
        result: Return code. 0 = success, non-zero = error.
        output: Optional output data.
    """
    reply: dict[str, Any] = {
        "tid": tid,
        "bid": bid,
        "method": method,
        "timestamp": int(__import__("time").time() * 1000),
        "data": {
            "result": result,
        },
    }
    if output:
        reply["data"]["output"] = output
    return reply

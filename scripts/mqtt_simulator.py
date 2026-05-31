"""DJI Dock 3 MQTT simulator for local development.

Publishes fake telemetry, state changes, and events to the local EMQX broker,
mimicking what a real Dock 3 + Matrice 4TD would send.

Usage:
    python scripts/mqtt_simulator.py

Requires: docker compose up (EMQX running on localhost:1883)
"""

import json
import math
import random
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

BROKER_HOST = "localhost"
BROKER_PORT = 1883

DOCK_SN = "DOCK3-TEST-001"
DRONE_SN = "M4TD-TEST-001"

# Simulated flight path around Athens (circular pattern)
CENTER_LAT = 37.9838
CENTER_LNG = 23.7275
RADIUS = 0.005  # ~500m radius


def make_osd_payload(step: int) -> dict:
    """Generate telemetry payload mimicking DJI Cloud API format."""
    angle = math.radians(step * 5)  # 5 degrees per step
    lat = CENTER_LAT + RADIUS * math.cos(angle)
    lng = CENTER_LNG + RADIUS * math.sin(angle)

    return {
        "tid": f"tid-{step}",
        "bid": f"bid-{step}",
        "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
        "data": {
            "latitude": lat,
            "longitude": lng,
            "height": 80.0 + random.uniform(-5, 5),
            "horizontal_speed": 5.0 + random.uniform(-1, 1),
            "vertical_speed": random.uniform(-0.5, 0.5),
            "attitude_head": (step * 5) % 360,
            "battery": {
                "capacity_percent": max(20, 95 - step * 0.5),
                "voltage": 44200 + random.randint(-500, 500),
                "temperature": 35.0 + random.uniform(-3, 3),
            },
            "wireless_link": {
                "quality": 90 + random.randint(-10, 10),
            },
            "mode_code": 0,  # 0=manual, 1=wayline, 15=return home
        },
    }


def make_state_payload(online: bool) -> dict:
    """Generate device state payload."""
    return {
        "tid": "state-001",
        "bid": "state-001",
        "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
        "data": {
            "online": online,
            "firmware_version": "01.00.0500",
            "device_model": "Dock 3",
        },
    }


def make_event_payload(event_type: str) -> dict:
    """Generate an async event payload."""
    return {
        "tid": f"evt-{event_type}",
        "bid": f"evt-{event_type}",
        "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
        "method": event_type,
        "data": {
            "status": "ok",
            "progress": 100 if event_type == "flighttask_progress" else 0,
        },
    }


def main() -> None:
    print(f"ASPIS MQTT Simulator")
    print(f"Connecting to {BROKER_HOST}:{BROKER_PORT}")
    print(f"Dock SN: {DOCK_SN}")
    print(f"Drone SN: {DRONE_SN}")
    print()

    client = mqtt.Client(
        client_id="aspis-simulator",
        protocol=mqtt.MQTTv311,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )

    # Subscribe to request replies so we can see cloud responses
    def on_message(client: mqtt.Client, userdata: object, msg: mqtt.MQTTMessage) -> None:
        data = json.loads(msg.payload)
        print(f"[REPLY] topic={msg.topic}  method={data.get('method')}  result={data.get('data', {}).get('result')}")

    client.on_message = on_message
    client.connect(BROKER_HOST, BROKER_PORT)
    client.subscribe(f"thing/product/{DOCK_SN}/requests_reply", qos=1)
    client.subscribe(f"thing/product/{DOCK_SN}/services", qos=1)
    client.loop_start()

    # Send initial device online state
    state_topic = f"thing/product/{DOCK_SN}/state"
    client.publish(state_topic, json.dumps(make_state_payload(True)), qos=1)
    print(f"[STATE] Dock online: {DOCK_SN}")

    drone_state_topic = f"thing/product/{DRONE_SN}/state"
    client.publish(drone_state_topic, json.dumps(make_state_payload(True)), qos=1)
    print(f"[STATE] Drone online: {DRONE_SN}")

    print()
    print("Sending telemetry (Ctrl+C to stop)...")
    print()

    step = 0
    try:
        while True:
            # Drone telemetry
            osd_topic = f"thing/product/{DRONE_SN}/osd"
            payload = make_osd_payload(step)
            client.publish(osd_topic, json.dumps(payload), qos=1)

            lat = payload["data"]["latitude"]
            lng = payload["data"]["longitude"]
            bat = payload["data"]["battery"]["capacity_percent"]
            spd = payload["data"]["horizontal_speed"]
            print(
                f"[OSD] step={step:4d}  lat={lat:.5f}  lng={lng:.5f}  "
                f"alt={payload['data']['height']:.1f}m  spd={spd:.1f}m/s  bat={bat:.1f}%"
            )

            # Dock heartbeat every 10 steps
            if step % 10 == 0:
                dock_osd = f"thing/product/{DOCK_SN}/osd"
                dock_payload = {
                    "data": {
                        "latitude": CENTER_LAT,
                        "longitude": CENTER_LNG,
                        "height": 0,
                        "horizontal_speed": 0,
                        "vertical_speed": 0,
                    }
                }
                client.publish(dock_osd, json.dumps(dock_payload), qos=1)

            # Simulate mission event at step 72 (one full circle)
            if step == 72:
                event_topic = f"thing/product/{DOCK_SN}/events"
                client.publish(
                    event_topic,
                    json.dumps(make_event_payload("flighttask_progress")),
                    qos=1,
                )
                print("[EVENT] Mission complete!")

            # Simulate config request at step 1 (dock asks for config on connect)
            if step == 1:
                request_topic = f"thing/product/{DOCK_SN}/requests"
                config_request = {
                    "tid": "config-001",
                    "bid": "config-001",
                    "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
                    "method": "config",
                    "data": {},
                }
                client.publish(request_topic, json.dumps(config_request), qos=1)
                print("[REQUEST] Dock requesting config")

            step += 1
            time.sleep(2)  # 0.5 Hz telemetry (per DJI Cloud API spec)

    except KeyboardInterrupt:
        print()
        print("Stopping simulator...")
        # Send offline state
        client.publish(state_topic, json.dumps(make_state_payload(False)), qos=1)
        client.publish(drone_state_topic, json.dumps(make_state_payload(False)), qos=1)
        print(f"[STATE] Devices offline")

    client.loop_stop()
    client.disconnect()
    print("Simulator stopped.")


if __name__ == "__main__":
    main()

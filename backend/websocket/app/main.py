"""ASPIS WebSocket Service -- real-time data push to operator dashboard.

Endpoints:
- /ws/telemetry/{site_id} -- live drone positions, battery, flight status
- /ws/alerts -- new alerts pushed in real-time

Backed by Redis pub/sub: MQTT consumer publishes, this service relays to clients.
"""

import structlog

logger = structlog.get_logger()


def main() -> None:
    logger.info("ASPIS WebSocket Service starting...")
    # TODO (Sprint 2): implement WebSocket server with Redis pub/sub
    logger.info("WebSocket Service placeholder -- implementation in Sprint 2")


if __name__ == "__main__":
    main()

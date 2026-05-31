"""Tests for DJI Cloud API topic parsing and message handling."""

import pytest

from backend.mqtt_consumer.app.dji_topics import (
    DJITopicType,
    ParsedTopic,
    parse_topic,
    parse_osd_payload,
    parse_state_payload,
    parse_event_payload,
    parse_request_payload,
    build_request_reply,
)


class TestTopicParsing:
    """Tests for MQTT topic string parsing."""

    def test_parse_osd_topic(self) -> None:
        result = parse_topic("thing/product/DOCK3-001/osd")
        assert result is not None
        assert result.device_sn == "DOCK3-001"
        assert result.topic_type == DJITopicType.OSD

    def test_parse_state_topic(self) -> None:
        result = parse_topic("thing/product/M4TD-001/state")
        assert result is not None
        assert result.device_sn == "M4TD-001"
        assert result.topic_type == DJITopicType.STATE

    def test_parse_events_topic(self) -> None:
        result = parse_topic("thing/product/DOCK3-001/events")
        assert result is not None
        assert result.topic_type == DJITopicType.EVENTS

    def test_parse_services_reply_topic(self) -> None:
        result = parse_topic("thing/product/DOCK3-001/services_reply")
        assert result is not None
        assert result.topic_type == DJITopicType.SERVICES_REPLY

    def test_parse_property_set_reply_topic(self) -> None:
        result = parse_topic("thing/product/DOCK3-001/property/set_reply")
        assert result is not None
        assert result.topic_type == DJITopicType.PROPERTY_SET_REPLY

    def test_parse_requests_topic(self) -> None:
        result = parse_topic("thing/product/DOCK3-001/requests")
        assert result is not None
        assert result.device_sn == "DOCK3-001"
        assert result.topic_type == DJITopicType.REQUESTS

    def test_parse_invalid_topic_returns_none(self) -> None:
        assert parse_topic("invalid/topic") is None
        assert parse_topic("thing/wrong/DOCK3-001/osd") is None
        assert parse_topic("") is None

    def test_parse_unknown_topic_type_returns_none(self) -> None:
        assert parse_topic("thing/product/DOCK3-001/unknown_type") is None


class TestOSDPayloadParsing:
    """Tests for OSD telemetry payload parsing."""

    def test_parse_simple_osd(self) -> None:
        payload = {
            "data": {
                "latitude": 37.9838,
                "longitude": 23.7275,
                "height": 120.5,
                "horizontal_speed": 5.2,
                "vertical_speed": -0.3,
                "attitude_head": 180.0,
                "battery": {"capacity_percent": 85.0},
                "wireless_link": {"quality": 95.0},
                "mode_code": 0,
            }
        }
        result = parse_osd_payload("DOCK3-001", payload)
        assert result.device_sn == "DOCK3-001"
        assert result.latitude == 37.9838
        assert result.longitude == 23.7275
        assert result.altitude == 120.5
        assert result.speed == 5.2
        assert result.battery_percent == 85.0
        assert result.signal_quality == 95.0
        assert result.heading == 180.0

    def test_parse_osd_with_sub_devices(self) -> None:
        payload = {
            "data": {
                "sub_devices": [
                    {
                        "data": {
                            "latitude": 38.0,
                            "longitude": 24.0,
                            "height": 100.0,
                            "horizontal_speed": 3.0,
                            "vertical_speed": 0.0,
                            "attitude_head": 90.0,
                            "battery": {"capacity_percent": 70.0},
                            "wireless_link": {"quality": 80.0},
                            "mode_code": 1,
                        }
                    }
                ]
            }
        }
        result = parse_osd_payload("DOCK3-001", payload)
        assert result.latitude == 38.0
        assert result.battery_percent == 70.0

    def test_parse_osd_missing_fields_uses_defaults(self) -> None:
        payload = {"data": {}}
        result = parse_osd_payload("DOCK3-001", payload)
        assert result.latitude == 0.0
        assert result.battery_percent == 0.0
        assert result.flight_mode == "unknown"


class TestStatePayloadParsing:
    """Tests for device state payload parsing."""

    def test_parse_state_online(self) -> None:
        payload = {
            "data": {
                "online": True,
                "firmware_version": "01.00.0500",
                "device_model": "Dock 3",
            }
        }
        result = parse_state_payload("DOCK3-001", payload)
        assert result.device_sn == "DOCK3-001"
        assert result.online is True
        assert result.firmware_version == "01.00.0500"

    def test_parse_state_offline(self) -> None:
        payload = {"data": {"online": False}}
        result = parse_state_payload("DOCK3-001", payload)
        assert result.online is False


class TestEventPayloadParsing:
    """Tests for event payload parsing."""

    def test_parse_mission_complete_event(self) -> None:
        payload = {
            "method": "flighttask_progress",
            "data": {
                "status": "ok",
                "progress": 100,
            }
        }
        result = parse_event_payload("DOCK3-001", payload)
        assert result.event_type == "flighttask_progress"
        assert result.event_data["status"] == "ok"

    def test_parse_media_available_event(self) -> None:
        payload = {
            "method": "file_upload_callback",
            "data": {
                "file": {"path": "/media/photo_001.jpg"},
            }
        }
        result = parse_event_payload("DOCK3-001", payload)
        assert result.event_type == "file_upload_callback"


class TestRequestPayloadParsing:
    """Tests for device request payload parsing."""

    def test_parse_config_request(self) -> None:
        payload = {
            "tid": "tid-001",
            "bid": "bid-001",
            "timestamp": 1654070968655,
            "method": "config",
            "data": {},
        }
        result = parse_request_payload("DOCK3-001", payload)
        assert result.gateway_sn == "DOCK3-001"
        assert result.tid == "tid-001"
        assert result.bid == "bid-001"
        assert result.method == "config"

    def test_parse_bind_status_request(self) -> None:
        payload = {
            "tid": "tid-002",
            "bid": "bid-002",
            "timestamp": 1654070968655,
            "method": "airport_bind_status",
            "data": {
                "bind_devices": [
                    {"device_binding_code": "abc123", "organization_id": "org-1"}
                ]
            },
        }
        result = parse_request_payload("DOCK3-001", payload)
        assert result.method == "airport_bind_status"
        assert len(result.request_data["bind_devices"]) == 1

    def test_parse_request_missing_fields(self) -> None:
        payload = {"data": {}}
        result = parse_request_payload("DOCK3-001", payload)
        assert result.tid == ""
        assert result.method == "unknown"


class TestRequestReplyBuilder:
    """Tests for building request reply payloads."""

    def test_build_success_reply(self) -> None:
        reply = build_request_reply(
            tid="tid-001", bid="bid-001", method="config", result=0
        )
        assert reply["tid"] == "tid-001"
        assert reply["bid"] == "bid-001"
        assert reply["method"] == "config"
        assert reply["data"]["result"] == 0
        assert "timestamp" in reply

    def test_build_reply_with_output(self) -> None:
        reply = build_request_reply(
            tid="tid-002",
            bid="bid-002",
            method="airport_organization_get",
            result=0,
            output={"organization_name": "IDS"},
        )
        assert reply["data"]["output"]["organization_name"] == "IDS"

    def test_build_error_reply(self) -> None:
        reply = build_request_reply(
            tid="tid-003", bid="bid-003", method="config", result=1
        )
        assert reply["data"]["result"] == 1

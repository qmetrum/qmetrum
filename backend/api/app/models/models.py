"""ASPIS database models -- all 10 core tables."""

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from backend.common.db.session import Base

# -- Enums --

class DockStatus(StrEnum):
    online = "online"
    offline = "offline"
    maintenance = "maintenance"
    error = "error"


class DroneStatus(StrEnum):
    idle = "idle"
    flying = "flying"
    charging = "charging"
    error = "error"
    offline = "offline"


class MissionType(StrEnum):
    patrol = "patrol"
    triggered = "triggered"
    manual = "manual"


class MissionStatus(StrEnum):
    pending = "pending"
    dispatched = "dispatched"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class DetectionType(StrEnum):
    smoke = "smoke"
    flame = "flame"
    thermal_anomaly = "thermal_anomaly"


class AlertSeverity(StrEnum):
    critical = "critical"
    warning = "warning"
    info = "info"


class AlertStatus(StrEnum):
    new = "new"
    acknowledged = "acknowledged"
    resolved = "resolved"
    false_positive = "false_positive"


class UserRole(StrEnum):
    admin = "admin"
    operator = "operator"
    viewer = "viewer"


class MediaType(StrEnum):
    photo = "photo"
    video = "video"
    thermal = "thermal"


class RiskLevel(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


# -- Models --

class Site(Base):
    __tablename__ = "sites"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    area_km2: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_level: Mapped[RiskLevel] = mapped_column(Enum(RiskLevel), default=RiskLevel.medium)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    docks: Mapped[list["Dock"]] = relationship(back_populates="site", lazy="selectin")
    missions: Mapped[list["Mission"]] = relationship(back_populates="site", lazy="selectin")
    waylines: Mapped[list["Wayline"]] = relationship(back_populates="site", lazy="selectin")


class Dock(Base):
    __tablename__ = "docks"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), nullable=False)
    serial_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    model: Mapped[str] = mapped_column(String(100), default="Dock 3")
    status: Mapped[DockStatus] = mapped_column(Enum(DockStatus), default=DockStatus.offline)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    firmware_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    site: Mapped["Site"] = relationship(back_populates="docks")
    drones: Mapped[list["Drone"]] = relationship(back_populates="dock", lazy="selectin")

    __table_args__ = (
        Index("ix_docks_site_id", "site_id"),
        Index("ix_docks_status", "status"),
    )


class Drone(Base):
    __tablename__ = "drones"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    dock_id: Mapped[str] = mapped_column(ForeignKey("docks.id"), nullable=False)
    serial_number: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    model: Mapped[str] = mapped_column(String(100), default="Matrice 4TD")
    battery_cycles: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[DroneStatus] = mapped_column(Enum(DroneStatus), default=DroneStatus.idle)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    dock: Mapped["Dock"] = relationship(back_populates="drones")
    missions: Mapped[list["Mission"]] = relationship(back_populates="drone", lazy="selectin")

    __table_args__ = (
        Index("ix_drones_dock_id", "dock_id"),
    )


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), nullable=False)
    dock_id: Mapped[str] = mapped_column(ForeignKey("docks.id"), nullable=False)
    drone_id: Mapped[str | None] = mapped_column(ForeignKey("drones.id"), nullable=True)
    wayline_id: Mapped[str | None] = mapped_column(ForeignKey("waylines.id"), nullable=True)
    type: Mapped[MissionType] = mapped_column(Enum(MissionType), nullable=False)
    status: Mapped[MissionStatus] = mapped_column(
        Enum(MissionStatus), default=MissionStatus.pending
    )
    flighthub_mission_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    site: Mapped["Site"] = relationship(back_populates="missions")
    dock: Mapped["Dock"] = relationship()
    drone: Mapped["Drone | None"] = relationship(back_populates="missions")
    wayline: Mapped["Wayline | None"] = relationship()
    detections: Mapped[list["Detection"]] = relationship(back_populates="mission", lazy="selectin")
    media: Mapped[list["Media"]] = relationship(back_populates="mission", lazy="selectin")

    __table_args__ = (
        Index("ix_missions_site_id", "site_id"),
        Index("ix_missions_status", "status"),
        Index("ix_missions_created_at", "created_at"),
    )


class Detection(Base):
    __tablename__ = "detections"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    mission_id: Mapped[str | None] = mapped_column(ForeignKey("missions.id"), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    altitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    detection_type: Mapped[DetectionType] = mapped_column(Enum(DetectionType), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    thermal_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    inference_source: Mapped[str] = mapped_column(String(20), default="edge")  # "edge" or "cloud"
    model_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    mission: Mapped["Mission | None"] = relationship(back_populates="detections")
    alert: Mapped["Alert | None"] = relationship(back_populates="detection", uselist=False)

    __table_args__ = (
        Index("ix_detections_mission_id", "mission_id"),
        Index("ix_detections_timestamp", "timestamp"),
        Index("ix_detections_detection_type", "detection_type"),
        Index("ix_detections_confidence", "confidence"),
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    detection_id: Mapped[str] = mapped_column(
        ForeignKey("detections.id"), unique=True, nullable=False
    )
    severity: Mapped[AlertSeverity] = mapped_column(Enum(AlertSeverity), nullable=False)
    status: Mapped[AlertStatus] = mapped_column(Enum(AlertStatus), default=AlertStatus.new)
    notified_via: Mapped[str | None] = mapped_column(String(255), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    detection: Mapped["Detection"] = relationship(back_populates="alert")

    __table_args__ = (
        Index("ix_alerts_status", "status"),
        Index("ix_alerts_severity", "severity"),
        Index("ix_alerts_created_at", "created_at"),
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.viewer)
    org_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_users_email", "email"),
    )


class Telemetry(Base):
    __tablename__ = "telemetry"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    drone_id: Mapped[str] = mapped_column(ForeignKey("drones.id"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    altitude: Mapped[float] = mapped_column(Float, nullable=False)
    speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    battery_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    signal_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    heading: Mapped[float | None] = mapped_column(Float, nullable=True)
    vertical_speed: Mapped[float | None] = mapped_column(Float, nullable=True)
    flight_mode: Mapped[str | None] = mapped_column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_telemetry_drone_id_timestamp", "drone_id", "timestamp"),
    )


class Wayline(Base):
    __tablename__ = "waylines"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    site_id: Mapped[str] = mapped_column(ForeignKey("sites.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    wpml_file_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    site: Mapped["Site"] = relationship(back_populates="waylines")

    __table_args__ = (
        Index("ix_waylines_site_id", "site_id"),
    )


class Media(Base):
    __tablename__ = "media"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), nullable=False)
    type: Mapped[MediaType] = mapped_column(Enum(MediaType), nullable=False)
    blob_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    mission: Mapped["Mission"] = relationship(back_populates="media")

    __table_args__ = (
        Index("ix_media_mission_id", "mission_id"),
        Index("ix_media_type", "type"),
    )

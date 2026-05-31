"""Seed the database with test data for local development."""

import asyncio
from datetime import datetime, timezone

from backend.common.config.settings import get_settings
from backend.common.db.session import async_session, engine, Base
from backend.api.app.models.models import (
    Site, Dock, Drone, User, Wayline,
    RiskLevel, DockStatus, DroneStatus, UserRole,
)

settings = get_settings()


async def seed() -> None:
    """Create test data."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session() as session:
        # Test site
        site = Site(
            name="ASPIS Test Site -- Attica",
            latitude=37.9838,
            longitude=23.7275,
            area_km2=5.0,
            risk_level=RiskLevel.high,
            description="Test deployment site in Attica region",
        )
        session.add(site)
        await session.flush()

        # Test dock
        dock = Dock(
            site_id=site.id,
            serial_number="DOCK3-TEST-001",
            model="Dock 3",
            status=DockStatus.online,
            last_heartbeat=datetime.now(timezone.utc),
            firmware_version="01.00.0500",
        )
        session.add(dock)
        await session.flush()

        # Test drone
        drone = Drone(
            dock_id=dock.id,
            serial_number="M4TD-TEST-001",
            model="Matrice 4TD",
            battery_cycles=12,
            status=DroneStatus.idle,
        )
        session.add(drone)

        # Admin user
        from passlib.context import CryptContext
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

        admin = User(
            email="admin@ids.gr",
            name="ASPIS Admin",
            hashed_password=pwd_context.hash("admin123"),
            role=UserRole.admin,
            org_id="ids",
        )
        session.add(admin)

        # Operator user
        operator = User(
            email="operator@ids.gr",
            name="ASPIS Operator",
            hashed_password=pwd_context.hash("operator123"),
            role=UserRole.operator,
            org_id="ids",
        )
        session.add(operator)
        await session.flush()

        # Test wayline
        wayline = Wayline(
            site_id=site.id,
            name="Patrol Route Alpha -- Perimeter",
            description="Standard perimeter patrol covering full site boundary",
            created_by=admin.id,
            version=1,
        )
        session.add(wayline)

        await session.commit()
        print("Seed data created successfully:")
        print(f"  Site: {site.name} ({site.id})")
        print(f"  Dock: {dock.serial_number} ({dock.id})")
        print(f"  Drone: {drone.serial_number} ({drone.id})")
        print(f"  Admin: {admin.email}")
        print(f"  Operator: {operator.email}")
        print(f"  Wayline: {wayline.name}")


if __name__ == "__main__":
    asyncio.run(seed())

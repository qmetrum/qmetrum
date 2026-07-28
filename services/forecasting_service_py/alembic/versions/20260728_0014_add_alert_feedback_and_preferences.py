"""add alertfeedback and useralertpreference

Revision ID: 20260728_0014
Revises: 20260607_0013
Create Date: 2026-07-28 00:00:00.000000

Two additive tables behind the alert feedback loop:

  alertfeedback        one user's verdict on one alert event
  useralertpreference  per-user notification behaviour (severity floor,
                       quiet hours, mutes)

Both are new tables with no changes to existing ones, so this is safe to apply
to a live database while the service is running. Absent rows mean defaults, so
users who never touch settings are unaffected.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260728_0014"
down_revision: Union[str, None] = "20260607_0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    try:
        return sa.inspect(bind).has_table(table_name)
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "alertfeedback"):
        op.create_table(
            "alertfeedback",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("alert_event_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("rating", sa.String(), nullable=False),
            sa.Column("reason", sa.String(), nullable=True),
            sa.Column("ticker", sa.String(), nullable=False, server_default=""),
            sa.Column("alert_kind", sa.String(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["alert_event_id"], ["alertevent.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.UniqueConstraint("alert_event_id", "user_id",
                                name="uq_alertfeedback_event_user"),
        )
        op.create_index("ix_alertfeedback_alert_event_id", "alertfeedback",
                        ["alert_event_id"])
        op.create_index("ix_alertfeedback_user_id", "alertfeedback", ["user_id"])
        op.create_index("ix_alertfeedback_rating", "alertfeedback", ["rating"])
        op.create_index("ix_alertfeedback_ticker", "alertfeedback", ["ticker"])
        op.create_index("ix_alertfeedback_alert_kind", "alertfeedback", ["alert_kind"])
        op.create_index("ix_alertfeedback_created_at", "alertfeedback", ["created_at"])

    if not _table_exists(bind, "useralertpreference"):
        op.create_table(
            "useralertpreference",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("email_enabled", sa.Boolean(), nullable=False,
                      server_default=sa.true()),
            sa.Column("min_severity", sa.String(), nullable=False,
                      server_default="ALERT"),
            sa.Column("quiet_hours_start", sa.Integer(), nullable=False,
                      server_default="0"),
            sa.Column("quiet_hours_end", sa.Integer(), nullable=False,
                      server_default="0"),
            sa.Column("quiet_hours_tz_offset_min", sa.Integer(), nullable=False,
                      server_default="0"),
            sa.Column("muted_tickers", sa.JSON(), nullable=True),
            sa.Column("muted_kinds", sa.JSON(), nullable=True),
            sa.Column("auto_mute_after", sa.Integer(), nullable=False,
                      server_default="3"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
            sa.UniqueConstraint("user_id", name="uq_useralertpreference_user"),
        )
        op.create_index("ix_useralertpreference_user_id", "useralertpreference",
                        ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "useralertpreference"):
        op.drop_table("useralertpreference")
    if _table_exists(bind, "alertfeedback"):
        op.drop_table("alertfeedback")

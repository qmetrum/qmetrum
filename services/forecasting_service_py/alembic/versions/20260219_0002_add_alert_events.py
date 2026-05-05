"""add alert event table

Revision ID: 20260219_0002
Revises: 20260219_0001
Create Date: 2026-02-19 00:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260219_0002"
down_revision: Union[str, None] = "20260219_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alertevent",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("alert_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("alert_type", sa.String(), nullable=False),
        sa.Column("triggered", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["alert_id"], ["alertrule.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alertevent_alert_id", "alertevent", ["alert_id"], unique=False)
    op.create_index("ix_alertevent_ticker", "alertevent", ["ticker"], unique=False)
    op.create_index("ix_alertevent_alert_type", "alertevent", ["alert_type"], unique=False)
    op.create_index("ix_alertevent_triggered", "alertevent", ["triggered"], unique=False)
    op.create_index("ix_alertevent_evaluated_at", "alertevent", ["evaluated_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_alertevent_evaluated_at", table_name="alertevent")
    op.drop_index("ix_alertevent_triggered", table_name="alertevent")
    op.drop_index("ix_alertevent_alert_type", table_name="alertevent")
    op.drop_index("ix_alertevent_ticker", table_name="alertevent")
    op.drop_index("ix_alertevent_alert_id", table_name="alertevent")
    op.drop_table("alertevent")

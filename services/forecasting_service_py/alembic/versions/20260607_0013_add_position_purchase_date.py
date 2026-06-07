"""add purchase_date to position

Revision ID: 20260607_0013
Revises: 20260504_0012
Create Date: 2026-06-07 00:00:00.000000

Enables holding-period / tax-lot accounting for positions that opt into
$-based tracking. Nullable so existing weight-only positions are unaffected.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260607_0013"
down_revision: Union[str, None] = "20260504_0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    try:
        return any(c.get("name") == column_name for c in inspector.get_columns(table_name))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    if not _column_exists(bind, "position", "purchase_date"):
        op.add_column("position", sa.Column("purchase_date", sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if _column_exists(bind, "position", "purchase_date"):
        op.drop_column("position", "purchase_date")

"""add regime thresholds table

Revision ID: 20260429_0011
Revises: 20260420_0010
Create Date: 2026-04-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260429_0011"
down_revision: Union[str, None] = "20260420_0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    try:
        return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "regimethreshold"):
        op.create_table(
            "regimethreshold",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("asset_class", sa.String(), nullable=False),
            sa.Column("high", sa.Float(), nullable=False, server_default="1.5"),
            sa.Column("low", sa.Float(), nullable=False, server_default="0.8"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("source", sa.String(), nullable=False, server_default="default-seed"),
            sa.Column("years_of_history", sa.Integer(), nullable=True),
            sa.Column("calibrated_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        for idx_name, cols in [
            ("ix_regimethreshold_asset_class", ["asset_class"]),
            ("ix_regimethreshold_is_active", ["is_active"]),
            ("ix_regimethreshold_calibrated_at", ["calibrated_at"]),
            ("ix_regimethreshold_created_at", ["created_at"]),
        ]:
            if not _index_exists(bind, "regimethreshold", idx_name):
                op.create_index(idx_name, "regimethreshold", cols, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "regimethreshold"):
        op.drop_table("regimethreshold")

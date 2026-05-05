"""add portfolio report data cache table

Revision ID: 20260318_0009
Revises: 20260316_0008
Create Date: 2026-03-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260318_0009"
down_revision: Union[str, None] = "20260316_0008"
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

    if not _table_exists(bind, "portfolioreportdatacache"):
        op.create_table(
            "portfolioreportdatacache",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("portfolio_id", sa.Integer(), nullable=False),
            sa.Column("input_hash", sa.String(), nullable=False),
            sa.Column("horizon_days", sa.Integer(), nullable=False, server_default="90"),
            sa.Column("data_last_date", sa.DateTime(), nullable=True),
            sa.Column("result_blob", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["portfolio_id"], ["portfolio.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("portfolio_id", "input_hash", name="uq_portfolioreportdatacache_key"),
        )
        for idx_name, cols in [
            ("ix_portfolioreportdatacache_portfolio_id", ["portfolio_id"]),
            ("ix_portfolioreportdatacache_input_hash", ["input_hash"]),
            ("ix_portfolioreportdatacache_horizon_days", ["horizon_days"]),
            ("ix_portfolioreportdatacache_data_last_date", ["data_last_date"]),
            ("ix_portfolioreportdatacache_created_at", ["created_at"]),
        ]:
            if not _index_exists(bind, "portfolioreportdatacache", idx_name):
                op.create_index(idx_name, "portfolioreportdatacache", cols, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "portfolioreportdatacache"):
        op.drop_table("portfolioreportdatacache")

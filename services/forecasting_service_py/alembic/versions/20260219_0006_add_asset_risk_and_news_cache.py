"""add asset risk cache and news cache tables

Revision ID: 20260219_0006
Revises: 20260219_0005
Create Date: 2026-02-26 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260219_0006"
down_revision: Union[str, None] = "20260219_0005"
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

    if not _table_exists(bind, "assetriskcache"):
        op.create_table(
            "assetriskcache",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("symbol", sa.String(), nullable=False),
            sa.Column("method", sa.String(), nullable=False),
            sa.Column("horizon_days", sa.Integer(), nullable=False),
            sa.Column("n_paths", sa.Integer(), nullable=False),
            sa.Column("data_last_date", sa.DateTime(), nullable=True),
            sa.Column("result_blob", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["symbol"], ["asset.symbol"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "symbol",
                "horizon_days",
                "n_paths",
                "method",
                "data_last_date",
                name="uq_assetriskcache_key",
            ),
        )

    for idx_name, cols in [
        ("ix_assetriskcache_symbol", ["symbol"]),
        ("ix_assetriskcache_method", ["method"]),
        ("ix_assetriskcache_horizon_days", ["horizon_days"]),
        ("ix_assetriskcache_n_paths", ["n_paths"]),
        ("ix_assetriskcache_data_last_date", ["data_last_date"]),
        ("ix_assetriskcache_created_at", ["created_at"]),
    ]:
        if not _index_exists(bind, "assetriskcache", idx_name):
            op.create_index(idx_name, "assetriskcache", cols, unique=False)

    if not _table_exists(bind, "newscache"):
        op.create_table(
            "newscache",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("symbol", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("limit_count", sa.Integer(), nullable=False),
            sa.Column("items_blob", sa.JSON(), nullable=False),
            sa.Column("fetched_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["symbol"], ["asset.symbol"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "symbol",
                "limit_count",
                "source",
                name="uq_newscache_symbol_limit_source",
            ),
        )

    for idx_name, cols in [
        ("ix_newscache_symbol", ["symbol"]),
        ("ix_newscache_source", ["source"]),
        ("ix_newscache_limit_count", ["limit_count"]),
        ("ix_newscache_fetched_at", ["fetched_at"]),
        ("ix_newscache_expires_at", ["expires_at"]),
    ]:
        if not _index_exists(bind, "newscache", idx_name):
            op.create_index(idx_name, "newscache", cols, unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "newscache"):
        for idx_name in [
            "ix_newscache_expires_at",
            "ix_newscache_fetched_at",
            "ix_newscache_limit_count",
            "ix_newscache_source",
            "ix_newscache_symbol",
        ]:
            if _index_exists(bind, "newscache", idx_name):
                op.drop_index(idx_name, table_name="newscache")
        op.drop_table("newscache")

    if _table_exists(bind, "assetriskcache"):
        for idx_name in [
            "ix_assetriskcache_created_at",
            "ix_assetriskcache_data_last_date",
            "ix_assetriskcache_n_paths",
            "ix_assetriskcache_horizon_days",
            "ix_assetriskcache_method",
            "ix_assetriskcache_symbol",
        ]:
            if _index_exists(bind, "assetriskcache", idx_name):
                op.drop_index(idx_name, table_name="assetriskcache")
        op.drop_table("assetriskcache")


"""add benchmark returns, asset returns, intraday quotes, and asset_class field

Revision ID: 20260316_0008
Revises: 20260227_0007
Create Date: 2026-03-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260316_0008"
down_revision: Union[str, None] = "20260227_0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    inspector = sa.inspect(bind)
    return table_name in inspector.get_table_names()


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    try:
        columns = [c["name"] for c in inspector.get_columns(table_name)]
        return column_name in columns
    except Exception:
        return False


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    try:
        return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()

    # -- Add asset_class column to asset table --
    if _table_exists(bind, "asset") and not _column_exists(bind, "asset", "asset_class"):
        op.add_column("asset", sa.Column("asset_class", sa.String(), nullable=False, server_default="US_EQUITY"))
        if not _index_exists(bind, "asset", "ix_asset_asset_class"):
            op.create_index("ix_asset_asset_class", "asset", ["asset_class"], unique=False)

    # -- IntraDayQuote table --
    if not _table_exists(bind, "intradayquote"):
        op.create_table(
            "intradayquote",
            sa.Column("symbol", sa.String(), nullable=False),
            sa.Column("last_price", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("change_pct", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("as_of", sa.DateTime(), nullable=False),
            sa.Column("source", sa.String(), nullable=False, server_default="yahoo"),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["symbol"], ["asset.symbol"]),
            sa.PrimaryKeyConstraint("symbol"),
        )
        if not _index_exists(bind, "intradayquote", "ix_intradayquote_as_of"):
            op.create_index("ix_intradayquote_as_of", "intradayquote", ["as_of"], unique=False)

    # -- BenchmarkReturn table --
    if not _table_exists(bind, "benchmarkreturn"):
        op.create_table(
            "benchmarkreturn",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("benchmark_symbol", sa.String(), nullable=False),
            sa.Column("date", sa.DateTime(), nullable=False),
            sa.Column("period", sa.String(), nullable=False, server_default="daily"),
            sa.Column("return_pct", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("cumulative_return", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("benchmark_symbol", "date", "period", name="uq_benchmarkreturn_key"),
        )
        for idx_name, cols in [
            ("ix_benchmarkreturn_benchmark_symbol", ["benchmark_symbol"]),
            ("ix_benchmarkreturn_date", ["date"]),
            ("ix_benchmarkreturn_period", ["period"]),
        ]:
            if not _index_exists(bind, "benchmarkreturn", idx_name):
                op.create_index(idx_name, "benchmarkreturn", cols, unique=False)

    # -- AssetReturn table --
    if not _table_exists(bind, "assetreturn"):
        op.create_table(
            "assetreturn",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("symbol", sa.String(), nullable=False),
            sa.Column("date", sa.DateTime(), nullable=False),
            sa.Column("period", sa.String(), nullable=False, server_default="daily"),
            sa.Column("return_pct", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["symbol"], ["asset.symbol"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("symbol", "date", "period", name="uq_assetreturn_key"),
        )
        for idx_name, cols in [
            ("ix_assetreturn_symbol", ["symbol"]),
            ("ix_assetreturn_date", ["date"]),
            ("ix_assetreturn_period", ["period"]),
        ]:
            if not _index_exists(bind, "assetreturn", idx_name):
                op.create_index(idx_name, "assetreturn", cols, unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "assetreturn"):
        op.drop_table("assetreturn")

    if _table_exists(bind, "benchmarkreturn"):
        op.drop_table("benchmarkreturn")

    if _table_exists(bind, "intradayquote"):
        op.drop_table("intradayquote")

    if _table_exists(bind, "asset") and _column_exists(bind, "asset", "asset_class"):
        if _index_exists(bind, "asset", "ix_asset_asset_class"):
            op.drop_index("ix_asset_asset_class", table_name="asset")
        op.drop_column("asset", "asset_class")

"""add asset volatility snapshot table

Revision ID: 20260227_0007
Revises: 20260219_0006
Create Date: 2026-02-27 15:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260227_0007"
down_revision: Union[str, None] = "20260219_0006"
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

    if not _table_exists(bind, "assetvolatilitysnapshot"):
        op.create_table(
            "assetvolatilitysnapshot",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("symbol", sa.String(), nullable=False),
            sa.Column("as_of", sa.DateTime(), nullable=False),
            sa.Column("method", sa.String(), nullable=False),
            sa.Column("horizon_days", sa.Integer(), nullable=False),
            sa.Column("n_paths", sa.Integer(), nullable=False),
            sa.Column("data_last_date", sa.DateTime(), nullable=True),
            sa.Column("sigma_latest", sa.Float(), nullable=True),
            sa.Column("sigma_next", sa.Float(), nullable=True),
            sa.Column("var_95_latest", sa.Float(), nullable=True),
            sa.Column("fragility_score_latest", sa.Float(), nullable=True),
            sa.Column("regime_latest", sa.String(), nullable=True),
            sa.Column("snapshot_blob", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["symbol"], ["asset.symbol"]),
            sa.PrimaryKeyConstraint("id"),
        )

    for idx_name, cols in [
        ("ix_assetvolatilitysnapshot_symbol", ["symbol"]),
        ("ix_assetvolatilitysnapshot_as_of", ["as_of"]),
        ("ix_assetvolatilitysnapshot_method", ["method"]),
        ("ix_assetvolatilitysnapshot_horizon_days", ["horizon_days"]),
        ("ix_assetvolatilitysnapshot_n_paths", ["n_paths"]),
        ("ix_assetvolatilitysnapshot_data_last_date", ["data_last_date"]),
        ("ix_assetvolatilitysnapshot_sigma_latest", ["sigma_latest"]),
        ("ix_assetvolatilitysnapshot_sigma_next", ["sigma_next"]),
        ("ix_assetvolatilitysnapshot_var_95_latest", ["var_95_latest"]),
        ("ix_assetvolatilitysnapshot_fragility_score_latest", ["fragility_score_latest"]),
        ("ix_assetvolatilitysnapshot_regime_latest", ["regime_latest"]),
        ("ix_assetvolatilitysnapshot_created_at", ["created_at"]),
    ]:
        if not _index_exists(bind, "assetvolatilitysnapshot", idx_name):
            op.create_index(idx_name, "assetvolatilitysnapshot", cols, unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "assetvolatilitysnapshot"):
        for idx_name in [
            "ix_assetvolatilitysnapshot_created_at",
            "ix_assetvolatilitysnapshot_regime_latest",
            "ix_assetvolatilitysnapshot_fragility_score_latest",
            "ix_assetvolatilitysnapshot_var_95_latest",
            "ix_assetvolatilitysnapshot_sigma_next",
            "ix_assetvolatilitysnapshot_sigma_latest",
            "ix_assetvolatilitysnapshot_data_last_date",
            "ix_assetvolatilitysnapshot_n_paths",
            "ix_assetvolatilitysnapshot_horizon_days",
            "ix_assetvolatilitysnapshot_method",
            "ix_assetvolatilitysnapshot_as_of",
            "ix_assetvolatilitysnapshot_symbol",
        ]:
            if _index_exists(bind, "assetvolatilitysnapshot", idx_name):
                op.drop_index(idx_name, table_name="assetvolatilitysnapshot")
        op.drop_table("assetvolatilitysnapshot")

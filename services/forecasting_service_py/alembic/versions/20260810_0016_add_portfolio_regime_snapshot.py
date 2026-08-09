"""add portfolioregimesnapshot

Revision ID: 20260810_0016
Revises: 20260806_0015
Create Date: 2026-08-10 00:00:00.000000

One additive table for the Regime Watch feature (Qpulse regime signal inside
Qsight): per-portfolio realized equity-vs-bond correlation vs the book's own
baseline. Kept SEPARATE from the public correlationsnapshot table because it is
private per-advisor data that must never leak through the public reader. Safe to
apply live.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260810_0016"
down_revision: Union[str, None] = "20260806_0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    try:
        return sa.inspect(bind).has_table(table_name)
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, "portfolioregimesnapshot"):
        op.create_table(
            "portfolioregimesnapshot",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("portfolio_id", sa.Integer(), nullable=False),
            sa.Column("pair", sa.String(), nullable=False, server_default="equity_vs_bond"),
            sa.Column("status", sa.String(), nullable=False, server_default="ok"),
            sa.Column("short_window", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("baseline_window", sa.Integer(), nullable=False, server_default="252"),
            sa.Column("short_corr", sa.Float(), nullable=False, server_default="0"),
            sa.Column("baseline_corr", sa.Float(), nullable=False, server_default="0"),
            sa.Column("delta", sa.Float(), nullable=False, server_default="0"),
            sa.Column("n_obs", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("as_of", sa.DateTime(), nullable=True),
            sa.Column("method", sa.String(), nullable=False, server_default=""),
            sa.Column("data_source", sa.String(), nullable=False, server_default=""),
            sa.Column("sleeve_weights_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("series_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("reason", sa.String(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["portfolio_id"], ["portfolio.id"]),
            sa.UniqueConstraint("portfolio_id", "short_window", "baseline_window",
                                name="uq_portfolioregimesnapshot_key"),
        )
        op.create_index("ix_portfolioregimesnapshot_portfolio_id", "portfolioregimesnapshot", ["portfolio_id"])
        op.create_index("ix_portfolioregimesnapshot_as_of", "portfolioregimesnapshot", ["as_of"])


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "portfolioregimesnapshot"):
        op.drop_table("portfolioregimesnapshot")

"""add correlationsnapshot and emailsignup

Revision ID: 20260806_0015
Revises: 20260728_0014
Create Date: 2026-08-06 00:00:00.000000

Two additive tables behind the free, no-login Cross-Asset Correlation Monitor:

  correlationsnapshot  one realized rolling correlation per pair per window,
                       precomputed by scripts/correlation_batch.py and served
                       by the public /public/correlations endpoint
  emailsignup          lead capture from the monitor (capture-only; no email
                       is sent — SES delivery is gated/off)

Both are new tables with no changes to existing ones, so this is safe to apply
to a live database while the service is running.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260806_0015"
down_revision: Union[str, None] = "20260728_0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(bind, table_name: str) -> bool:
    try:
        return sa.inspect(bind).has_table(table_name)
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "correlationsnapshot"):
        op.create_table(
            "correlationsnapshot",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("pair_key", sa.String(), nullable=False),
            sa.Column("symbol_a", sa.String(), nullable=False),
            sa.Column("symbol_b", sa.String(), nullable=False),
            sa.Column("label", sa.String(), nullable=False, server_default=""),
            sa.Column("window_days", sa.Integer(), nullable=False),
            sa.Column("as_of", sa.DateTime(), nullable=False),
            sa.Column("corr_pearson", sa.Float(), nullable=False, server_default="0"),
            sa.Column("corr_spearman", sa.Float(), nullable=False, server_default="0"),
            sa.Column("n_obs", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("method", sa.String(), nullable=False, server_default=""),
            sa.Column("data_source", sa.String(), nullable=False, server_default=""),
            sa.Column("series_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("pair_key", "window_days",
                                name="uq_correlationsnapshot_pair_window"),
        )
        op.create_index("ix_correlationsnapshot_pair_key", "correlationsnapshot", ["pair_key"])
        op.create_index("ix_correlationsnapshot_window_days", "correlationsnapshot", ["window_days"])
        op.create_index("ix_correlationsnapshot_as_of", "correlationsnapshot", ["as_of"])

    if not _table_exists(bind, "emailsignup"):
        op.create_table(
            "emailsignup",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
            sa.Column("email", sa.String(), nullable=False),
            sa.Column("source", sa.String(), nullable=False,
                      server_default="correlation_monitor"),
            sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("email", name="uq_emailsignup_email"),
        )
        op.create_index("ix_emailsignup_email", "emailsignup", ["email"], unique=True)
        op.create_index("ix_emailsignup_source", "emailsignup", ["source"])
        op.create_index("ix_emailsignup_created_at", "emailsignup", ["created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "emailsignup"):
        op.drop_table("emailsignup")
    if _table_exists(bind, "correlationsnapshot"):
        op.drop_table("correlationsnapshot")

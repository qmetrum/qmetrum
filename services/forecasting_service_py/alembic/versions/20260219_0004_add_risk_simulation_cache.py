"""add risk simulation cache table

Revision ID: 20260219_0004
Revises: 20260219_0003
Create Date: 2026-02-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260219_0004"
down_revision: Union[str, None] = "20260219_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "risksimulationcache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("n_simulations", sa.Integer(), nullable=False),
        sa.Column("random_seed", sa.Integer(), nullable=True),
        sa.Column("input_hash", sa.String(), nullable=False),
        sa.Column("data_last_date", sa.DateTime(), nullable=True),
        sa.Column("result_blob", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_type",
            "entity_id",
            "method",
            "input_hash",
            name="uq_risksimulationcache_key",
        ),
    )
    op.create_index("ix_risksimulationcache_entity_type", "risksimulationcache", ["entity_type"], unique=False)
    op.create_index("ix_risksimulationcache_entity_id", "risksimulationcache", ["entity_id"], unique=False)
    op.create_index("ix_risksimulationcache_method", "risksimulationcache", ["method"], unique=False)
    op.create_index("ix_risksimulationcache_horizon_days", "risksimulationcache", ["horizon_days"], unique=False)
    op.create_index("ix_risksimulationcache_random_seed", "risksimulationcache", ["random_seed"], unique=False)
    op.create_index("ix_risksimulationcache_input_hash", "risksimulationcache", ["input_hash"], unique=False)
    op.create_index("ix_risksimulationcache_data_last_date", "risksimulationcache", ["data_last_date"], unique=False)
    op.create_index("ix_risksimulationcache_created_at", "risksimulationcache", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_risksimulationcache_created_at", table_name="risksimulationcache")
    op.drop_index("ix_risksimulationcache_data_last_date", table_name="risksimulationcache")
    op.drop_index("ix_risksimulationcache_input_hash", table_name="risksimulationcache")
    op.drop_index("ix_risksimulationcache_random_seed", table_name="risksimulationcache")
    op.drop_index("ix_risksimulationcache_horizon_days", table_name="risksimulationcache")
    op.drop_index("ix_risksimulationcache_method", table_name="risksimulationcache")
    op.drop_index("ix_risksimulationcache_entity_id", table_name="risksimulationcache")
    op.drop_index("ix_risksimulationcache_entity_type", table_name="risksimulationcache")
    op.drop_table("risksimulationcache")

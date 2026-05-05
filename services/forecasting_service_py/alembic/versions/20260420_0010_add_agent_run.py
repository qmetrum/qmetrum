"""add agent run log table

Revision ID: 20260420_0010
Revises: 20260318_0009
Create Date: 2026-04-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260420_0010"
down_revision: Union[str, None] = "20260318_0009"
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

    if not _table_exists(bind, "agentrun"):
        op.create_table(
            "agentrun",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("agent_name", sa.String(), nullable=False),
            sa.Column("model", sa.String(), nullable=False),
            sa.Column("input_hash", sa.String(), nullable=False),
            sa.Column("output", sa.Text(), nullable=False, server_default=""),
            sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(), nullable=False, server_default="ok"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("extra", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        for idx_name, cols in [
            ("ix_agentrun_agent_name", ["agent_name"]),
            ("ix_agentrun_model", ["model"]),
            ("ix_agentrun_input_hash", ["input_hash"]),
            ("ix_agentrun_status", ["status"]),
            ("ix_agentrun_created_at", ["created_at"]),
        ]:
            if not _index_exists(bind, "agentrun", idx_name):
                op.create_index(idx_name, "agentrun", cols, unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, "agentrun"):
        op.drop_table("agentrun")

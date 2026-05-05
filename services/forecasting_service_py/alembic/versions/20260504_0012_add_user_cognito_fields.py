"""add cognito_sub + name to user table

Revision ID: 20260504_0012
Revises: 20260429_0011
Create Date: 2026-05-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260504_0012"
down_revision: Union[str, None] = "20260429_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_exists(bind, table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(bind)
    try:
        return any(c.get("name") == column_name for c in inspector.get_columns(table_name))
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

    if not _column_exists(bind, "user", "cognito_sub"):
        op.add_column("user", sa.Column("cognito_sub", sa.String(), nullable=True))
    if not _column_exists(bind, "user", "name"):
        op.add_column("user", sa.Column("name", sa.String(), nullable=True))

    if not _index_exists(bind, "user", "ix_user_cognito_sub"):
        op.create_index("ix_user_cognito_sub", "user", ["cognito_sub"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    if _index_exists(bind, "user", "ix_user_cognito_sub"):
        op.drop_index("ix_user_cognito_sub", table_name="user")
    if _column_exists(bind, "user", "name"):
        op.drop_column("user", "name")
    if _column_exists(bind, "user", "cognito_sub"):
        op.drop_column("user", "cognito_sub")

"""add user ownership model

Revision ID: 20260219_0003
Revises: 20260219_0002
Create Date: 2026-02-19 00:40:00.000000

"""
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260219_0003"
down_revision: Union[str, None] = "20260219_0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_email", "user", ["email"], unique=True)
    op.create_index("ix_user_is_active", "user", ["is_active"], unique=False)

    user_table = sa.table(
        "user",
        sa.column("id", sa.Integer),
        sa.column("email", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    now = datetime.utcnow()
    op.bulk_insert(
        user_table,
        [
            {
                "id": 1,
                "email": "local@qmetrum.dev",
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        ],
    )

    with op.batch_alter_table("portfolio") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=False, server_default=sa.text("1")))
        batch.create_index("ix_portfolio_user_id", ["user_id"], unique=False)
        batch.create_foreign_key("fk_portfolio_user_id_user", "user", ["user_id"], ["id"])
        batch.alter_column("user_id", server_default=None)

    with op.batch_alter_table("watchlist") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=False, server_default=sa.text("1")))
        batch.create_index("ix_watchlist_user_id", ["user_id"], unique=False)
        batch.create_foreign_key("fk_watchlist_user_id_user", "user", ["user_id"], ["id"])
        batch.alter_column("user_id", server_default=None)

    with op.batch_alter_table("alertrule") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=False, server_default=sa.text("1")))
        batch.create_index("ix_alertrule_user_id", ["user_id"], unique=False)
        batch.create_foreign_key("fk_alertrule_user_id_user", "user", ["user_id"], ["id"])
        batch.alter_column("user_id", server_default=None)

    with op.batch_alter_table("savedscreen") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=False, server_default=sa.text("1")))
        batch.create_index("ix_savedscreen_user_id", ["user_id"], unique=False)
        batch.create_foreign_key("fk_savedscreen_user_id_user", "user", ["user_id"], ["id"])
        batch.alter_column("user_id", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("savedscreen") as batch:
        batch.drop_constraint("fk_savedscreen_user_id_user", type_="foreignkey")
        batch.drop_index("ix_savedscreen_user_id")
        batch.drop_column("user_id")

    with op.batch_alter_table("alertrule") as batch:
        batch.drop_constraint("fk_alertrule_user_id_user", type_="foreignkey")
        batch.drop_index("ix_alertrule_user_id")
        batch.drop_column("user_id")

    with op.batch_alter_table("watchlist") as batch:
        batch.drop_constraint("fk_watchlist_user_id_user", type_="foreignkey")
        batch.drop_index("ix_watchlist_user_id")
        batch.drop_column("user_id")

    with op.batch_alter_table("portfolio") as batch:
        batch.drop_constraint("fk_portfolio_user_id_user", type_="foreignkey")
        batch.drop_index("ix_portfolio_user_id")
        batch.drop_column("user_id")

    op.drop_index("ix_user_is_active", table_name="user")
    op.drop_index("ix_user_email", table_name="user")
    op.drop_table("user")

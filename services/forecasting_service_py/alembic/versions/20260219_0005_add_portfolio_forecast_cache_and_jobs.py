"""add portfolio forecast cache and forecast jobs

Revision ID: 20260219_0005
Revises: 20260219_0004
Create Date: 2026-02-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260219_0005"
down_revision: Union[str, None] = "20260219_0004"
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

    if not _table_exists(bind, "portfolioforecastcache"):
        op.create_table(
            "portfolioforecastcache",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("owner_user_id", sa.Integer(), nullable=False),
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("entity_id", sa.String(), nullable=False),
            sa.Column("input_hash", sa.String(), nullable=False),
            sa.Column("horizon_days", sa.Integer(), nullable=False),
            sa.Column("data_last_date", sa.DateTime(), nullable=True),
            sa.Column("request_payload", sa.JSON(), nullable=False),
            sa.Column("result_blob", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["owner_user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "owner_user_id",
                "entity_type",
                "entity_id",
                "input_hash",
                name="uq_portfolioforecastcache_key",
            ),
        )

    for idx_name, cols in [
        ("ix_portfolioforecastcache_owner_user_id", ["owner_user_id"]),
        ("ix_portfolioforecastcache_entity_type", ["entity_type"]),
        ("ix_portfolioforecastcache_entity_id", ["entity_id"]),
        ("ix_portfolioforecastcache_input_hash", ["input_hash"]),
        ("ix_portfolioforecastcache_horizon_days", ["horizon_days"]),
        ("ix_portfolioforecastcache_data_last_date", ["data_last_date"]),
        ("ix_portfolioforecastcache_created_at", ["created_at"]),
        ("ix_portfolioforecastcache_updated_at", ["updated_at"]),
    ]:
        if not _index_exists(bind, "portfolioforecastcache", idx_name):
            op.create_index(idx_name, "portfolioforecastcache", cols, unique=False)

    if not _table_exists(bind, "forecastjob"):
        op.create_table(
            "forecastjob",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("owner_user_id", sa.Integer(), nullable=False),
            sa.Column("job_type", sa.String(), nullable=False),
            sa.Column("entity_type", sa.String(), nullable=False),
            sa.Column("entity_id", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("request_hash", sa.String(), nullable=False),
            sa.Column("request_payload", sa.JSON(), nullable=False),
            sa.Column("progress", sa.Float(), nullable=False),
            sa.Column("error_message", sa.String(), nullable=True),
            sa.Column("result_cache_id", sa.Integer(), nullable=True),
            sa.Column("result_blob", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["owner_user_id"], ["user.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    for idx_name, cols in [
        ("ix_forecastjob_owner_user_id", ["owner_user_id"]),
        ("ix_forecastjob_job_type", ["job_type"]),
        ("ix_forecastjob_entity_type", ["entity_type"]),
        ("ix_forecastjob_entity_id", ["entity_id"]),
        ("ix_forecastjob_status", ["status"]),
        ("ix_forecastjob_request_hash", ["request_hash"]),
        ("ix_forecastjob_result_cache_id", ["result_cache_id"]),
        ("ix_forecastjob_created_at", ["created_at"]),
        ("ix_forecastjob_started_at", ["started_at"]),
        ("ix_forecastjob_finished_at", ["finished_at"]),
        ("ix_forecastjob_updated_at", ["updated_at"]),
    ]:
        if not _index_exists(bind, "forecastjob", idx_name):
            op.create_index(idx_name, "forecastjob", cols, unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "forecastjob"):
        for idx_name in [
            "ix_forecastjob_updated_at",
            "ix_forecastjob_finished_at",
            "ix_forecastjob_started_at",
            "ix_forecastjob_created_at",
            "ix_forecastjob_result_cache_id",
            "ix_forecastjob_request_hash",
            "ix_forecastjob_status",
            "ix_forecastjob_entity_id",
            "ix_forecastjob_entity_type",
            "ix_forecastjob_job_type",
            "ix_forecastjob_owner_user_id",
        ]:
            if _index_exists(bind, "forecastjob", idx_name):
                op.drop_index(idx_name, table_name="forecastjob")
        op.drop_table("forecastjob")

    if _table_exists(bind, "portfolioforecastcache"):
        for idx_name in [
            "ix_portfolioforecastcache_updated_at",
            "ix_portfolioforecastcache_created_at",
            "ix_portfolioforecastcache_data_last_date",
            "ix_portfolioforecastcache_horizon_days",
            "ix_portfolioforecastcache_input_hash",
            "ix_portfolioforecastcache_entity_id",
            "ix_portfolioforecastcache_entity_type",
            "ix_portfolioforecastcache_owner_user_id",
        ]:
            if _index_exists(bind, "portfolioforecastcache", idx_name):
                op.drop_index(idx_name, table_name="portfolioforecastcache")
        op.drop_table("portfolioforecastcache")


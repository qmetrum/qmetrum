"""create initial schema

Revision ID: 20260219_0001
Revises:
Create Date: 2026-02-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260219_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset",
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("asset_type", sa.String(), nullable=False),
        sa.Column("exchange", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=False),
        sa.Column("vendor", sa.String(), nullable=False),
        sa.Column("vendor_symbol", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("symbol"),
    )
    op.create_index("ix_asset_asset_type", "asset", ["asset_type"], unique=False)

    op.create_table(
        "forecastcache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("run_date", sa.DateTime(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("winner_model", sa.String(), nullable=False),
        sa.Column("model_version", sa.String(), nullable=False),
        sa.Column("training_window_start", sa.DateTime(), nullable=True),
        sa.Column("training_window_end", sa.DateTime(), nullable=True),
        sa.Column("data_last_date", sa.DateTime(), nullable=True),
        sa.Column("forecast_blob", sa.JSON(), nullable=False),
        sa.Column("final_predicted_price", sa.Float(), nullable=False),
        sa.Column("fragility_score", sa.Float(), nullable=False),
        sa.Column("var_95", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_forecastcache_ticker", "forecastcache", ["ticker"], unique=False)
    op.create_index("ix_forecastcache_run_date", "forecastcache", ["run_date"], unique=False)

    op.create_table(
        "portfolio",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "fundamentalssnapshot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("as_of", sa.DateTime(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("asset_type", sa.String(), nullable=False),
        sa.Column("sector", sa.String(), nullable=True),
        sa.Column("industry", sa.String(), nullable=True),
        sa.Column("currency", sa.String(), nullable=True),
        sa.Column("market_cap", sa.Float(), nullable=True),
        sa.Column("pe_ratio", sa.Float(), nullable=True),
        sa.Column("ev_to_ebitda", sa.Float(), nullable=True),
        sa.Column("beta", sa.Float(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["symbol"], ["asset.symbol"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fundamentalssnapshot_symbol", "fundamentalssnapshot", ["symbol"], unique=False)
    op.create_index("ix_fundamentalssnapshot_as_of", "fundamentalssnapshot", ["as_of"], unique=False)
    op.create_index("ix_fundamentalssnapshot_asset_type", "fundamentalssnapshot", ["asset_type"], unique=False)
    op.create_index("ix_fundamentalssnapshot_sector", "fundamentalssnapshot", ["sector"], unique=False)
    op.create_index("ix_fundamentalssnapshot_market_cap", "fundamentalssnapshot", ["market_cap"], unique=False)

    op.create_table(
        "marketdata",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["symbol"], ["asset.symbol"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", "date", name="uq_marketdata_symbol_date"),
    )
    op.create_index("ix_marketdata_symbol", "marketdata", ["symbol"], unique=False)
    op.create_index("ix_marketdata_date", "marketdata", ["date"], unique=False)

    op.create_table(
        "position",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("portfolio_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("cost_basis", sa.Float(), nullable=False),
        sa.Column("asset_type", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["portfolio_id"], ["portfolio.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_position_portfolio_id", "position", ["portfolio_id"], unique=False)
    op.create_index("ix_position_ticker", "position", ["ticker"], unique=False)

    op.create_table(
        "watchlistitem",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("watchlist_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("note", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["watchlist_id"], ["watchlist.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_watchlistitem_watchlist_id", "watchlistitem", ["watchlist_id"], unique=False)
    op.create_index("ix_watchlistitem_ticker", "watchlistitem", ["ticker"], unique=False)

    op.create_table(
        "alertrule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("watchlist_id", sa.Integer(), nullable=True),
        sa.Column("alert_type", sa.String(), nullable=False),
        sa.Column("direction", sa.String(), nullable=False),
        sa.Column("threshold_value", sa.Float(), nullable=False),
        sa.Column("lookback_days", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("extra_config", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["watchlist_id"], ["watchlist.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_alertrule_ticker", "alertrule", ["ticker"], unique=False)
    op.create_index("ix_alertrule_watchlist_id", "alertrule", ["watchlist_id"], unique=False)
    op.create_index("ix_alertrule_alert_type", "alertrule", ["alert_type"], unique=False)
    op.create_index("ix_alertrule_is_active", "alertrule", ["is_active"], unique=False)

    op.create_table(
        "savedscreen",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("savedscreen")

    op.drop_index("ix_alertrule_is_active", table_name="alertrule")
    op.drop_index("ix_alertrule_alert_type", table_name="alertrule")
    op.drop_index("ix_alertrule_watchlist_id", table_name="alertrule")
    op.drop_index("ix_alertrule_ticker", table_name="alertrule")
    op.drop_table("alertrule")

    op.drop_index("ix_watchlistitem_ticker", table_name="watchlistitem")
    op.drop_index("ix_watchlistitem_watchlist_id", table_name="watchlistitem")
    op.drop_table("watchlistitem")

    op.drop_index("ix_position_ticker", table_name="position")
    op.drop_index("ix_position_portfolio_id", table_name="position")
    op.drop_table("position")

    op.drop_index("ix_marketdata_date", table_name="marketdata")
    op.drop_index("ix_marketdata_symbol", table_name="marketdata")
    op.drop_table("marketdata")

    op.drop_index("ix_fundamentalssnapshot_market_cap", table_name="fundamentalssnapshot")
    op.drop_index("ix_fundamentalssnapshot_sector", table_name="fundamentalssnapshot")
    op.drop_index("ix_fundamentalssnapshot_asset_type", table_name="fundamentalssnapshot")
    op.drop_index("ix_fundamentalssnapshot_as_of", table_name="fundamentalssnapshot")
    op.drop_index("ix_fundamentalssnapshot_symbol", table_name="fundamentalssnapshot")
    op.drop_table("fundamentalssnapshot")

    op.drop_table("watchlist")
    op.drop_table("portfolio")

    op.drop_index("ix_forecastcache_run_date", table_name="forecastcache")
    op.drop_index("ix_forecastcache_ticker", table_name="forecastcache")
    op.drop_table("forecastcache")

    op.drop_index("ix_asset_asset_type", table_name="asset")
    op.drop_table("asset")

"""Flush forecast caches so subsequent requests regenerate with the new response shape.

Clears only the forecast-level caches (asset forecast, portfolio forecast, nightly
portfolio data blob). Risk caches (AssetRiskCache, AssetVolatilitySnapshot) are left
untouched because they hold R-service output that has not changed.

Usage:
    python scripts/flush_forecast_caches.py [--dry-run] [--asset] [--portfolio] [--nightly] [--all]

Defaults: --all (clear all three caches).
"""

from __future__ import annotations

import argparse

from sqlmodel import Session, delete, select

from app.db.database import engine
from app.db.models import (
    ForecastCache,
    PortfolioForecastCache,
    PortfolioReportDataCache,
)


def _count(session: Session, model) -> int:
    return len(session.exec(select(model)).all())


def main() -> None:
    parser = argparse.ArgumentParser(description="Flush forecast caches.")
    parser.add_argument("--dry-run", action="store_true", help="Report counts, do not delete.")
    parser.add_argument("--asset", action="store_true", help="Clear ForecastCache (per-asset).")
    parser.add_argument("--portfolio", action="store_true", help="Clear PortfolioForecastCache.")
    parser.add_argument("--nightly", action="store_true", help="Clear PortfolioReportDataCache.")
    parser.add_argument("--all", action="store_true", help="Clear all three (default).")
    args = parser.parse_args()

    if args.all or not (args.asset or args.portfolio or args.nightly):
        args.asset = args.portfolio = args.nightly = True

    with Session(engine) as session:
        targets = []
        if args.asset:
            targets.append(("ForecastCache", ForecastCache))
        if args.portfolio:
            targets.append(("PortfolioForecastCache", PortfolioForecastCache))
        if args.nightly:
            targets.append(("PortfolioReportDataCache", PortfolioReportDataCache))

        for name, model in targets:
            before = _count(session, model)
            if args.dry_run:
                print(f"{name}: {before} rows (dry-run, not deleted)")
                continue
            session.exec(delete(model))
            session.commit()
            after = _count(session, model)
            print(f"{name}: {before} rows -> {after} rows")

    print("Done. Subsequent forecast requests will recompute against the new response shape.")


if __name__ == "__main__":
    main()

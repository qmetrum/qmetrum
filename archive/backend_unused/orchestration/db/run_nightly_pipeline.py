# orchestration/run_nightly_pipeline.py

import sys
import os
import logging
from datetime import datetime
from sqlmodel import Session, select

# Fix path to import from services/
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'services', 'forecasting_service_py')))

from app.db.database import engine, init_db
from app.db.models import Asset, MarketData, Fundamentals
from app.utils.data_fetcher import fetch_stock_data, fetch_fundamentals

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("NightlyPipeline")

def update_assets():
    """
    1. Reads all assets tracked in the DB.
    2. Fetches fresh data (Price + Fundamentals).
    3. Updates the DB.
    """
    with Session(engine) as session:
        # Get all tracked assets
        assets = session.exec(select(Asset)).all()
        logger.info(f"Starting nightly update for {len(assets)} assets...")

        for asset in assets:
            try:
                logger.info(f"Updating {asset.ticker}...")
                
                # A. Update Price History (MarketData)
                # Fetch only last 5 days to be safe/fast, or full if needed
                # For simplicity, we fetch standard 2y and upsert new rows
                # (In production, you'd fetch only 'new' data)
                raw_data = fetch_stock_data(asset.ticker, period="5d") 
                
                for row in raw_data:
                    # Check if exists (composite key ticker+date)
                    existing = session.exec(
                        select(MarketData).where(
                            MarketData.ticker == asset.ticker,
                            MarketData.date == datetime.strptime(row['date'], '%Y-%m-%d')
                        )
                    ).first()
                    
                    if not existing:
                        md = MarketData(
                            ticker=asset.ticker,
                            date=datetime.strptime(row['date'], '%Y-%m-%d'),
                            open=0.0, # Yahoo fetcher in simple mode might only give Close
                            high=0.0, 
                            low=0.0,
                            close=row['price'],
                            volume=row.get('volume', 0)
                        )
                        session.add(md)

                # B. Update Fundamentals
                fund_data = fetch_fundamentals(asset.ticker)
                
                # Check if we have an existing record
                existing_fund = session.exec(select(Fundamentals).where(Fundamentals.ticker == asset.ticker)).first()
                
                if not existing_fund:
                    existing_fund = Fundamentals(ticker=asset.ticker)
                    session.add(existing_fund)
                
                # Update fields (Generic mapping)
                if 'valuation' in fund_data:
                    existing_fund.pe_ratio = fund_data['valuation'].get('pe_ratio')
                    existing_fund.sector = fund_data['profile'].get('sector')
                    existing_fund.market_cap = fund_data['valuation'].get('market_cap')
                
                # Commit per asset to save progress
                session.commit()
                
            except Exception as e:
                logger.error(f"Failed to update {asset.ticker}: {e}")
                session.rollback()

if __name__ == "__main__":
    logger.info("--- NIGHTLY PIPELINE STARTED ---")
    # Ensure DB tables exist
    init_db()
    
    # Run Update
    update_assets()
    
    logger.info("--- NIGHTLY PIPELINE COMPLETE ---")
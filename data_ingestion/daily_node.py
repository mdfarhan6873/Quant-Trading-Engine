import asyncio
import logging
import time
from datetime import datetime
import nsepython
from core.redis_client import redis_db
from core.config import settings

logger = logging.getLogger(__name__)

class DailyDataNode:
    """
    Handles all "Once-a-day" and "At-boot" data fetching defined in DATA_SOURCES.md.
    - Previous Day OHLC (9:00 AM)
    - NSE Circuit Breakers (9:00 AM)
    - ForexFactory Calendar (8:00 AM)
    - FII/DII Data (Post 6:00 PM)
    """
    def __init__(self):
        self.is_running = False

    async def fetch_boot_data(self):
        """Fetches data that must exist in Redis before the market opens."""
        logger.info("Fetching Boot-time Daily Data...")
        try:
            import yfinance as yf
            
            # 1. Previous Day OHLC dynamically fetched via yfinance
            nifty_ticker = yf.Ticker("^NSEI") 
            banknifty_ticker = yf.Ticker("^NSEBANK")
            
            n_hist = nifty_ticker.history(period="5d") 
            bn_hist = banknifty_ticker.history(period="5d")
            
            pd_ohlc = {}
            circuit_breakers = {}
            
            if len(n_hist) >= 1:
                pd_row = n_hist.iloc[-1]
                prev_close = float(pd_row["Close"])
                pd_ohlc["NIFTY50"] = {
                    "open": float(pd_row["Open"]), "high": float(pd_row["High"]), 
                    "low": float(pd_row["Low"]), "close": prev_close
                }
                circuit_breakers["NIFTY50"] = {
                    "10_pct_down": round(prev_close * 0.90, 2), 
                    "15_pct_down": round(prev_close * 0.85, 2), 
                    "20_pct_down": round(prev_close * 0.80, 2)
                }

            if len(bn_hist) >= 1:
                pd_row = bn_hist.iloc[-1]
                prev_close = float(pd_row["Close"])
                pd_ohlc["BANKNIFTY"] = {
                    "open": float(pd_row["Open"]), "high": float(pd_row["High"]), 
                    "low": float(pd_row["Low"]), "close": prev_close
                }
                circuit_breakers["BANKNIFTY"] = {
                    "10_pct_down": round(prev_close * 0.90, 2), 
                    "15_pct_down": round(prev_close * 0.85, 2), 
                    "20_pct_down": round(prev_close * 0.80, 2)
                }
                
            await redis_db.set_json("PREV_DAY_OHLC", pd_ohlc)
            await redis_db.set_json("CIRCUIT_BREAKERS", circuit_breakers)
            logger.info("Dynamically calculated PDH/PDL and Circuit Breakers for NIFTY50 and BANKNIFTY.")
            
            # 3. Macro Calendar Events
            await redis_db.set_json("MACRO_CALENDAR", {"events": []})
            
            logger.info("Boot-time Data successfully loaded into Redis.")
        except Exception as e:
            logger.error(f"Failed to fetch boot data: {e}")

    async def fetch_eod_data(self):
        """Fetches End of Day data (FII/DII) via nsepython."""
        logger.info("Fetching EOD FII/DII Data...")
        try:
            # Use nsepython to fetch FII/DII data
            fii_dii = nsepython.fii_dii()
            await redis_db.set_json("FII_DII_DATA", fii_dii)
            logger.info("FII/DII Data successfully loaded into Redis.")
        except Exception as e:
            logger.error(f"Failed to fetch FII/DII data: {e}")

    async def run(self):
        """Background loop to trigger fetches at specific times of the day."""
        self.is_running = True
        logger.info("Daily Data Node started.")
        
        # Always run boot data once on startup
        await self.fetch_boot_data()
        
        while self.is_running:
            now = datetime.now()
            
            # Example time-based triggers
            if now.hour == 18 and now.minute == 30: # 6:30 PM
                await self.fetch_eod_data()
                await asyncio.sleep(60) # Sleep for a minute to prevent multiple triggers
                
            if now.hour == 8 and now.minute == 0: # 8:00 AM
                await self.fetch_boot_data()
                await asyncio.sleep(60)
                
            await asyncio.sleep(30) # Check time every 30 seconds

    async def stop(self):
        self.is_running = False
        logger.info("Daily Data Node stopped.")

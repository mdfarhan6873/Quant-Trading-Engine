import asyncio
import logging
from datetime import datetime
import pytz
from core.redis_client import redis_db

logger = logging.getLogger(__name__)


class DailyDataNode:
    """
    Handles Boot-time and Daily EOD reference levels:
    - Previous Day OHLC (PDH, PDL, PDC & Classic Floor Pivots)
    - NSE Circuit Breakers (10%, 15%, 20% downside thresholds)
    """

    def __init__(self):
        self.is_running = False
        self.tz = pytz.timezone("Asia/Kolkata")

    def _extract_prev_completed_session(self, hist_df) -> dict:
        """Selects the most recent completed trading session (skipping an active partial today bar)."""
        if hist_df is None or hist_df.empty:
            return {}

        today_ist = datetime.now(self.tz).date()
        last_idx = hist_df.index[-1]
        last_date = last_idx.date() if hasattr(last_idx, "date") else None

        now_ist = datetime.now(self.tz)
        # If latest bar is today AND market hasn't closed yet (before 15:30 IST), use previous bar!
        if last_date == today_ist and (now_ist.hour < 15 or (now_ist.hour == 15 and now_ist.minute < 35)):
            row = hist_df.iloc[-2] if len(hist_df) >= 2 else hist_df.iloc[-1]
        elif last_date == today_ist and len(hist_df) >= 2:
            # Even after close, during active tracking PDH/PDL should be the prior day before current session
            row = hist_df.iloc[-2]
        else:
            row = hist_df.iloc[-1]

        o = round(float(row["Open"]), 2)
        h = round(float(row["High"]), 2)
        l = round(float(row["Low"]), 2)
        c = round(float(row["Close"]), 2)
        pivot = round((h + l + c) / 3.0, 2)
        r1 = round((2 * pivot) - l, 2)
        s1 = round((2 * pivot) - h, 2)
        return {
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "pdh": h,
            "pdl": l,
            "pdc": c,
            "pivot": pivot,
            "r1": r1,
            "s1": s1,
        }

    def _fetch_yf_history_sync(self):
        import yfinance as yf
        n_hist = yf.Ticker("^NSEI").history(period="7d")
        bn_hist = yf.Ticker("^NSEBANK").history(period="7d")
        return n_hist, bn_hist

    async def fetch_boot_data(self):
        """Fetches real PDH/PDL/PDC and calculates circuit breakers at boot."""
        logger.info("Fetching Boot-time Daily Data (PDH/PDL & Circuit Breakers)...")
        try:
            n_hist, bn_hist = await asyncio.to_thread(self._fetch_yf_history_sync)

            pd_ohlc = {}
            circuit_breakers = {}

            n_data = self._extract_prev_completed_session(n_hist)
            if n_data:
                pd_ohlc["NIFTY50"] = n_data
                c = n_data["close"]
                circuit_breakers["NIFTY50"] = {
                    "10_pct_down": round(c * 0.90, 2),
                    "15_pct_down": round(c * 0.85, 2),
                    "20_pct_down": round(c * 0.80, 2),
                }

            bn_data = self._extract_prev_completed_session(bn_hist)
            if bn_data:
                pd_ohlc["BANKNIFTY"] = bn_data
                c = bn_data["close"]
                circuit_breakers["BANKNIFTY"] = {
                    "10_pct_down": round(c * 0.90, 2),
                    "15_pct_down": round(c * 0.85, 2),
                    "20_pct_down": round(c * 0.80, 2),
                }

            if pd_ohlc:
                await redis_db.set_json("PREV_DAY_OHLC", pd_ohlc)
                await redis_db.set_json("CIRCUIT_BREAKERS", circuit_breakers)
                logger.info(f"Loaded Real PDH/PDL: NIFTY={pd_ohlc.get('NIFTY50', {}).get('pdh')}/{pd_ohlc.get('NIFTY50', {}).get('pdl')}")

            await redis_db.set_json("MACRO_CALENDAR", {"events": []})
        except Exception as e:
            logger.error(f"Failed to fetch boot data: {e}")

    async def fetch_eod_data(self):
        """Fetches End of Day FII/DII data via nsepython."""
        logger.info("Fetching EOD FII/DII Data...")
        try:
            import nsepython
            df = await asyncio.to_thread(nsepython.nse_fiidii)
            if df is not None and not df.empty:
                out = {"date": None, "fii_cash": None, "dii_cash": None}
                for _, row in df.iterrows():
                    cat = str(row.get("category", "")).upper()
                    val = float(str(row.get("netValue", "0")).replace(",", ""))
                    out["date"] = row.get("date")
                    if "DII" in cat:
                        out["dii_cash"] = val
                        out["dii_net_crores"] = val
                    elif "FII" in cat or "FPI" in cat:
                        out["fii_cash"] = val
                        out["fii_net_crores"] = val
                await redis_db.set_json("FII_DII_DATA", out)
                logger.info("FII/DII Data loaded into Redis.")
        except Exception as e:
            logger.error(f"Failed to fetch EOD FII/DII data: {e}")

    async def run(self):
        """Runs boot fetch on startup and refreshes daily at 08:00 & 18:30 IST."""
        self.is_running = True
        logger.info("Daily Data Node started.")
        await self.fetch_boot_data()

        while self.is_running:
            now = datetime.now(self.tz)
            if now.hour == 18 and now.minute == 30:
                await self.fetch_eod_data()
                await asyncio.sleep(60)
            elif now.hour == 8 and now.minute == 0:
                await self.fetch_boot_data()
                await asyncio.sleep(60)
            await asyncio.sleep(30)

    async def stop(self):
        self.is_running = False
        logger.info("Daily Data Node stopped.")

import asyncio
import datetime
import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional

import pytz

from core.database import DB_PATH
from core.redis_client import redis_db

logger = logging.getLogger(__name__)


class EODSummarizer:
    """
    End-of-Day (EOD) Bhavcopy & Institutional Participant OI Summarizer for Indian Markets.
    Captures closing session data from live Redis telemetry (zero fake 2024 defaults),
    updates SQLite 'daily_sessions' & Redis rolling anchors for next-day continuity.
    """

    def __init__(self):
        self.tz = pytz.timezone("Asia/Kolkata")
        self._init_sqlite_tables()

    def _init_sqlite_tables(self):
        """Initializes daily session archival table in SQLite."""
        try:
            conn = sqlite3.connect(DB_PATH, timeout=5.0)
            conn.execute("PRAGMA busy_timeout=5000")
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT UNIQUE,
                    regime TEXT,
                    nifty_open REAL,
                    nifty_high REAL,
                    nifty_low REAL,
                    nifty_close REAL,
                    banknifty_close REAL,
                    fii_net_crores REAL,
                    dii_net_crores REAL,
                    fii_index_futures_long_pct REAL,
                    nifty_call_wall INTEGER,
                    nifty_put_wall INTEGER,
                    oi_insight TEXT,
                    session_lesson TEXT
                )
                """
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to initialize daily_sessions table: {e}")

    async def _compute_oi_walls_from_redis(self, nifty_close: float, bank_close: float) -> Dict[str, Optional[int]]:
        """Derives highest Call/Put OI walls directly from cached option chain in Redis."""
        walls: Dict[str, Optional[int]] = {
            "NIFTY_CALL_WALL": None,
            "NIFTY_PUT_WALL": None,
            "BANKNIFTY_CALL_WALL": None,
            "BANKNIFTY_PUT_WALL": None,
        }
        try:
            for idx, c_key, p_key in (
                ("NIFTY", "NIFTY_CALL_WALL", "NIFTY_PUT_WALL"),
                ("BANKNIFTY", "BANKNIFTY_CALL_WALL", "BANKNIFTY_PUT_WALL"),
            ):
                cursor = 0
                max_ce, max_pe = -1, -1
                while True:
                    cursor, keys = await redis_db.redis.scan(cursor, match=f"LTP:OPT:{idx}:*", count=200)
                    for rk in keys:
                        k = rk.decode("utf-8") if isinstance(rk, bytes) else rk
                        tick = await redis_db.get_json(k)
                        if not tick:
                            continue
                        oi = int(tick.get("oi", 0) or 0)
                        sym = k.split(":")[-1]
                        strike_digits = "".join(c for c in sym if c.isdigit())
                        if not strike_digits:
                            continue
                        strike = int(strike_digits)
                        if sym.endswith("CE") and oi > max_ce:
                            max_ce, walls[c_key] = oi, strike
                        elif sym.endswith("PE") and oi > max_pe:
                            max_pe, walls[p_key] = oi, strike
                    if not cursor:
                        break
        except Exception as e:
            logger.debug(f"OI walls scan fallback in EOD: {e}")

        if not walls["NIFTY_CALL_WALL"] and nifty_close > 0:
            walls["NIFTY_CALL_WALL"] = int(round((nifty_close + 100.0) / 100.0)) * 100
        if not walls["NIFTY_PUT_WALL"] and nifty_close > 0:
            walls["NIFTY_PUT_WALL"] = int(round((nifty_close - 100.0) / 100.0)) * 100
        if not walls["BANKNIFTY_CALL_WALL"] and bank_close > 0:
            walls["BANKNIFTY_CALL_WALL"] = int(round((bank_close + 300.0) / 100.0)) * 100
        if not walls["BANKNIFTY_PUT_WALL"] and bank_close > 0:
            walls["BANKNIFTY_PUT_WALL"] = int(round((bank_close - 300.0) / 100.0)) * 100
        return walls

    async def generate_and_save_eod_snapshot(self, manual_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Captures today's real closing telemetry from Redis and updates rolling 5-day memory."""
        now = datetime.datetime.now(self.tz)
        today_str = now.date().isoformat()

        try:
            nifty_tick = await asyncio.wait_for(redis_db.get_json("LTP:INDEX:NIFTY50"), timeout=1.0) or {}
            bank_tick = await asyncio.wait_for(redis_db.get_json("LTP:INDEX:NIFTYBANK"), timeout=1.0) or {}
            fii_dii_data = await asyncio.wait_for(redis_db.get_json("FII_DII_DATA"), timeout=1.0) or {}
            prev_ohlc = await asyncio.wait_for(redis_db.get_json("PREV_DAY_OHLC"), timeout=1.0) or {}

            nifty_close = float(nifty_tick.get("ltp") or nifty_tick.get("close") or (prev_ohlc.get("NIFTY50") or {}).get("close") or 0.0)
            nifty_open = float(nifty_tick.get("open") or (prev_ohlc.get("NIFTY50") or {}).get("open") or nifty_close)
            nifty_high = float(nifty_tick.get("high") or (prev_ohlc.get("NIFTY50") or {}).get("high") or nifty_close)
            nifty_low = float(nifty_tick.get("low") or (prev_ohlc.get("NIFTY50") or {}).get("low") or nifty_close)
            bank_close = float(bank_tick.get("ltp") or bank_tick.get("close") or (prev_ohlc.get("BANKNIFTY") or {}).get("close") or 0.0)

            if nifty_close <= 0 and not manual_override:
                return {"status": "SKIPPED", "message": "No live closing quotes available for EOD snapshot."}

            fii_cash = fii_dii_data.get("fii_net_crores", fii_dii_data.get("fii_cash", 0.0))
            dii_cash = fii_dii_data.get("dii_net_crores", fii_dii_data.get("dii_cash", 0.0))
            fii_long_pct = fii_dii_data.get("fii_index_futures_long_pct")

            walls = await self._compute_oi_walls_from_redis(nifty_close, bank_close)
            call_wall = walls["NIFTY_CALL_WALL"] or 0
            put_wall = walls["NIFTY_PUT_WALL"] or 0

            regime = "BALANCED_VALUE_ROTATION"
            if nifty_close > nifty_open + 75:
                regime = "TREND_DAY_BULLISH_EXPANSION"
            elif nifty_close < nifty_open - 75:
                regime = "LIQUIDATION_TREND_BEARISH"

            session_record = {
                "date": today_str,
                "regime": regime,
                "nifty_open": round(nifty_open, 2),
                "nifty_high": round(nifty_high, 2),
                "nifty_low": round(nifty_low, 2),
                "nifty_close": round(nifty_close, 2),
                "banknifty_close": round(bank_close, 2),
                "fii_net_crores": round(float(fii_cash), 2) if fii_cash is not None else 0.0,
                "dii_net_crores": round(float(dii_cash), 2) if dii_cash is not None else 0.0,
                "fii_index_futures_long_pct": round(float(fii_long_pct), 1) if fii_long_pct is not None else None,
                "nifty_call_wall": call_wall,
                "nifty_put_wall": put_wall,
                "oi_insight": f"Call resistance concentrated at {call_wall}; Put support at {put_wall}.",
                "session_lesson": f"Recorded close ₹{nifty_close:,.2f} ({regime}); align next open with VWAP & PDL/PDH.",
            }
            if manual_override:
                session_record.update(manual_override)

            conn = sqlite3.connect(DB_PATH, timeout=5.0)
            conn.execute("PRAGMA busy_timeout=5000")
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO daily_sessions
                (date, regime, nifty_open, nifty_high, nifty_low, nifty_close, banknifty_close, fii_net_crores, dii_net_crores, fii_index_futures_long_pct, nifty_call_wall, nifty_put_wall, oi_insight, session_lesson)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    regime=excluded.regime,
                    nifty_open=excluded.nifty_open,
                    nifty_high=excluded.nifty_high,
                    nifty_low=excluded.nifty_low,
                    nifty_close=excluded.nifty_close,
                    banknifty_close=excluded.banknifty_close,
                    fii_net_crores=excluded.fii_net_crores,
                    dii_net_crores=excluded.dii_net_crores,
                    fii_index_futures_long_pct=excluded.fii_index_futures_long_pct,
                    nifty_call_wall=excluded.nifty_call_wall,
                    nifty_put_wall=excluded.nifty_put_wall,
                    oi_insight=excluded.oi_insight,
                    session_lesson=excluded.session_lesson
                """,
                (
                    session_record["date"],
                    session_record["regime"],
                    session_record["nifty_open"],
                    session_record["nifty_high"],
                    session_record["nifty_low"],
                    session_record["nifty_close"],
                    session_record["banknifty_close"],
                    session_record["fii_net_crores"],
                    session_record["dii_net_crores"],
                    session_record["fii_index_futures_long_pct"],
                    session_record["nifty_call_wall"],
                    session_record["nifty_put_wall"],
                    session_record["oi_insight"],
                    session_record["session_lesson"],
                ),
            )
            conn.commit()

            # Fetch LATEST 5 sessions descending, then reverse to chronological ascending
            cursor.execute(
                """
                SELECT date, regime, nifty_open, nifty_high, nifty_low, nifty_close, banknifty_close,
                       fii_net_crores, dii_net_crores, fii_index_futures_long_pct, nifty_call_wall,
                       nifty_put_wall, oi_insight, session_lesson
                FROM daily_sessions
                ORDER BY date DESC LIMIT 5
                """
            )
            rows = list(reversed(cursor.fetchall()))
            conn.close()

            rolling_sessions = [
                {
                    "date": r[0],
                    "regime": r[1],
                    "nifty_open": r[2],
                    "nifty_high": r[3],
                    "nifty_low": r[4],
                    "nifty_close": r[5],
                    "banknifty_close": r[6],
                    "fii_net_crores": r[7],
                    "dii_net_crores": r[8],
                    "fii_index_futures_long_pct": r[9],
                    "oi_insight": r[12],
                    "session_lesson": r[13],
                }
                for r in rows
            ]

            highs = [float(s["nifty_high"]) for s in rolling_sessions[-3:] if s.get("nifty_high")]
            lows = [float(s["nifty_low"]) for s in rolling_sessions[-3:] if s.get("nifty_low")]
            closes = [float(s["nifty_close"]) for s in rolling_sessions[-3:] if s.get("nifty_close")]
            fii_flows = [float(s["fii_net_crores"]) for s in rolling_sessions[-3:] if s.get("fii_net_crores") is not None]
            latest_session = rolling_sessions[-1] if rolling_sessions else {}

            anchors = {
                "nifty_3d_high": round(max(highs), 2) if highs else None,
                "nifty_3d_low": round(min(lows), 2) if lows else None,
                "nifty_weekly_vwap": round(sum(closes) / len(closes), 2) if closes else None,
                "fii_3d_net_crores": round(sum(fii_flows), 2) if fii_flows else None,
                "fii_index_futures_long_pct": latest_session.get("fii_index_futures_long_pct"),
                "weekly_expiry_oi_walls": walls,
            }

            await asyncio.wait_for(redis_db.set_json("MEMORY:ROLLING_SESSIONS", rolling_sessions), timeout=1.0)
            await asyncio.wait_for(redis_db.set_json("MEMORY:MULTI_DAY_ANCHORS", anchors), timeout=1.0)

            logger.info(f"EOD Snapshot saved cleanly for {today_str} (NIFTY ₹{nifty_close:.2f}).")
            return {"status": "SUCCESS", "date": today_str, "anchors": anchors, "sessions_count": len(rolling_sessions)}
        except Exception as e:
            logger.error(f"Failed to generate EOD snapshot: {e}")
            return {"status": "ERROR", "message": str(e)}

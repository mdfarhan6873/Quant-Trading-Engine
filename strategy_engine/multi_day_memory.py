import asyncio
import datetime
import json
import logging
import os
import sqlite3
from typing import Any, Dict, List

import pytz
from core.database import DB_PATH
from core.redis_client import redis_db

logger = logging.getLogger(__name__)


class MultiDayMemoryEngine:
    """
    Rolling 3-to-5 Day Indian Market Auction Continuity Engine (NSE NIFTY & BANK NIFTY).
    Builds real 3-Day High/Low, Weekly VWAP proxy, Institutional OI Walls, FII/DII flow,
    and SQLite trade history reflections from actual market sessions.
    """

    def __init__(self):
        self.tz = pytz.timezone("Asia/Kolkata")
        self.redis_key_sessions = "MEMORY:ROLLING_SESSIONS"
        self.redis_key_anchors = "MEMORY:MULTI_DAY_ANCHORS"
        self.redis_key_reflection = "MEMORY:SESSION_REFLECTIONS"

    async def get_multi_day_context(self) -> Dict[str, Any]:
        """Retrieves rolling multi-day intelligence from Redis/SQLite/Yahoo Finance."""
        try:
            raw_sessions = await redis_db.redis.get(self.redis_key_sessions)
            sessions = json.loads(raw_sessions) if raw_sessions else []

            # Invalidate stale/old cached sessions if live spot diverges > 10% or sessions missing
            needs_refresh = not sessions
            if sessions:
                nifty_tick = await redis_db.get_json("LTP:INDEX:NIFTY50") or {}
                live_spot = float(nifty_tick.get("ltp", 0) or 0)
                cached_close = float(sessions[-1].get("nifty_close", 0) or 0)
                if live_spot > 0 and cached_close > 0 and abs(live_spot - cached_close) / live_spot > 0.10:
                    needs_refresh = True

            if needs_refresh:
                await self._seed_real_multi_day_history()
                raw_sessions = await redis_db.redis.get(self.redis_key_sessions)
                sessions = json.loads(raw_sessions) if raw_sessions else []

            # Compute live Call Wall & Put Wall dynamically from current Option Chain OI in Redis
            oi_walls = await self._compute_live_oi_walls()
            fii_dii = await redis_db.get_json("FII_DII_DATA") or {}
            anchors = self._calculate_real_anchors(sessions, oi_walls, fii_dii)

            await redis_db.set_json(self.redis_key_anchors, anchors)
            engine_experience = self._get_recent_engine_experience(days=3)
            structural_bias = self._synthesize_structural_bias(sessions, anchors)

            return {
                "rolling_window": "3_DAY_AUCTION_CONTINUITY",
                "structural_bias": structural_bias,
                "anchors": anchors,
                "prior_sessions": sessions[-3:],
                "engine_experience": engine_experience,
            }
        except Exception as e:
            logger.error(f"Failed to compile Multi-Day Memory: {e}")
            return {
                "rolling_window": "3_DAY_FALLBACK",
                "structural_bias": "AWAITING_SESSION_HISTORY",
                "anchors": {},
                "prior_sessions": [],
                "engine_experience": {"recent_trades_count": 0, "win_rate": "N/A", "realized_pnl": 0.0},
            }

    async def _compute_live_oi_walls(self) -> Dict[str, int]:
        """Finds the exact strikes with highest CE OI (Call Wall) and PE OI (Put Wall)."""
        walls = {
            "NIFTY_CALL_WALL": 0,
            "NIFTY_PUT_WALL": 0,
            "BANKNIFTY_CALL_WALL": 0,
            "BANKNIFTY_PUT_WALL": 0,
        }
        for prefix in ("NIFTY", "BANKNIFTY"):
            max_ce_oi, max_ce_strike = -1.0, 0
            max_pe_oi, max_pe_strike = -1.0, 0
            cursor = 0
            try:
                while True:
                    cursor, keys = await redis_db.redis.scan(cursor, match=f"LTP:OPT:{prefix}:*", count=200)
                    for rk in keys:
                        k = rk.decode("utf-8") if isinstance(rk, bytes) else rk
                        raw = await redis_db.redis.get(k)
                        if not raw:
                            continue
                        d = json.loads(raw)
                        sym = d.get("symbol", "")
                        oi = float(d.get("oi", 0) or 0)
                        parts = sym.split(":")
                        if len(parts) < 3 or oi <= 0:
                            continue
                        strike = int(float(parts[2][:-2]))
                        if sym.endswith("CE") and oi > max_ce_oi:
                            max_ce_oi, max_ce_strike = oi, strike
                        elif sym.endswith("PE") and oi > max_pe_oi:
                            max_pe_oi, max_pe_strike = oi, strike
                    if not cursor:
                        break
            except Exception:
                pass
            if max_ce_strike > 0:
                walls[f"{prefix}_CALL_WALL"] = max_ce_strike
            if max_pe_strike > 0:
                walls[f"{prefix}_PUT_WALL"] = max_pe_strike
        return walls

    def _calculate_real_anchors(
        self,
        sessions: List[Dict[str, Any]],
        oi_walls: Dict[str, int] = None,
        fii_dii: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """Calculates real 3-day extremes, rolling weekly benchmark, and FII flows from real sessions."""
        if not sessions:
            return {
                "nifty_3d_high": None,
                "nifty_3d_low": None,
                "nifty_weekly_vwap": None,
                "banknifty_3d_high": None,
                "banknifty_3d_low": None,
                "banknifty_weekly_vwap": None,
                "fii_3d_net_crores": fii_dii.get("fii_net_crores") if fii_dii else None,
                "fii_index_futures_long_pct": None,
                "weekly_expiry_oi_walls": oi_walls or {},
            }

        recent = sessions[-3:]
        n_highs = [float(s["nifty_high"]) for s in recent if s.get("nifty_high")]
        n_lows = [float(s["nifty_low"]) for s in recent if s.get("nifty_low")]
        n_closes = [float(s["nifty_close"]) for s in sessions[-5:] if s.get("nifty_close")]

        bn_highs = [float(s["banknifty_high"]) for s in recent if s.get("banknifty_high")]
        bn_lows = [float(s["banknifty_low"]) for s in recent if s.get("banknifty_low")]
        bn_closes = [float(s["banknifty_close"]) for s in sessions[-5:] if s.get("banknifty_close")]

        fii_flows = [float(s["fii_net_crores"]) for s in recent if s.get("fii_net_crores") is not None]
        fii_total = round(sum(fii_flows), 2) if fii_flows else (fii_dii.get("fii_net_crores") if fii_dii else None)

        return {
            "nifty_3d_high": round(max(n_highs), 2) if n_highs else None,
            "nifty_3d_low": round(min(n_lows), 2) if n_lows else None,
            "nifty_weekly_vwap": round(sum(n_closes) / len(n_closes), 2) if n_closes else None,
            "banknifty_3d_high": round(max(bn_highs), 2) if bn_highs else None,
            "banknifty_3d_low": round(min(bn_lows), 2) if bn_lows else None,
            "banknifty_weekly_vwap": round(sum(bn_closes) / len(bn_closes), 2) if bn_closes else None,
            "fii_3d_net_crores": fii_total,
            "fii_index_futures_long_pct": None,
            "weekly_expiry_oi_walls": oi_walls or {},
        }

    def _synthesize_structural_bias(self, sessions: List[Dict[str, Any]], anchors: Dict[str, Any]) -> str:
        """Determines overarching auction structure from real recent sessions and FII net flow."""
        fii_flow = anchors.get("fii_3d_net_crores")
        if fii_flow is None:
            if len(sessions) >= 2 and sessions[-1].get("nifty_close") and sessions[-2].get("nifty_close"):
                if sessions[-1]["nifty_close"] > sessions[-2]["nifty_close"]:
                    return "HIGHER_VALUE_ACCEPTANCE (Bullish Session Continuity)"
                return "LOWER_VALUE_MIGRATION (Respect Downside Liquidity)"
            return "RANGE_BOUND_AUCTION (Tracking Live Boundaries)"
        if fii_flow < -3000:
            return "INSTITUTIONAL_SUPPLY_PRESSURE (FII Net Sellers — Respect Resistance)"
        elif fii_flow > 3000:
            return "INSTITUTIONAL_ACCUMULATION (FII Net Buyers — Buy Pullbacks to VWAP)"
        return "BALANCED_AUCTION_CONTINUITY (Respect 3-Day High/Low Boundaries)"

    def _get_recent_engine_experience(self, days: int = 3) -> Dict[str, Any]:
        """Pulls real trade logs from SQLite to extract actual execution metrics."""
        if not os.path.exists(DB_PATH):
            return {
                "recent_trades_count": 0,
                "win_rate": "N/A",
                "realized_pnl": 0.0,
                "key_lesson": "Engine initialized. Awaiting high-conviction setup (>90% confluence).",
            }

        try:
            conn = sqlite3.connect(DB_PATH, timeout=5.0)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT action, pnl, confidence, reason, timestamp
                FROM trade_logs
                ORDER BY id DESC LIMIT 20
                """
            )
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                min_conf = getattr(__import__("core.config", fromlist=["settings"]).settings, "LLM_MIN_CONFIDENCE", 78)
                return {
                    "recent_trades_count": 0,
                    "win_rate": "N/A",
                    "realized_pnl": 0.0,
                    "key_lesson": f"Zero recorded trades yet. Strict {min_conf}%+ confluence & Patience Protocol active.",
                }

            total_trades = len(rows)
            wins = sum(1 for r in rows if (r["pnl"] or 0) > 0)
            losses = sum(1 for r in rows if (r["pnl"] or 0) < 0)
            net_pnl = sum((r["pnl"] or 0) for r in rows)
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

            return {
                "recent_trades_count": total_trades,
                "wins": wins,
                "losses": losses,
                "win_rate": f"{win_rate:.1f}%",
                "realized_pnl_inr": round(net_pnl, 2),
                "key_lesson": f"{total_trades} closed/logged executions audited (Win Rate {win_rate:.1f}%, Net ₹{net_pnl:+.0f}).",
            }
        except Exception as e:
            logger.error(f"Failed to query trade history: {e}")
            return {"recent_trades_count": 0, "win_rate": "N/A", "realized_pnl": 0.0}

    def _fetch_real_sessions_sync(self) -> List[Dict[str, Any]]:
        """Pulls real last 5 trading days OHLC from Yahoo Finance (^NSEI, ^NSEBANK) and daily_sessions DB."""
        sessions: List[Dict[str, Any]] = []

        # 1. Try SQLite daily_sessions first if available
        if os.path.exists(DB_PATH):
            try:
                conn = sqlite3.connect(DB_PATH, timeout=5.0)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM daily_sessions ORDER BY date DESC LIMIT 5"
                ).fetchall()
                conn.close()
                for r in reversed(rows):
                    sessions.append(dict(r))
            except Exception:
                pass

        # 2. Fetch authentic exchange daily bars via yfinance to supplement / hydrate
        try:
            import yfinance as yf
            n_df = yf.Ticker("^NSEI").history(period="7d")
            bn_df = yf.Ticker("^NSEBANK").history(period="7d")
            if not n_df.empty:
                bn_map = {}
                if not bn_df.empty:
                    for idx, brow in bn_df.iterrows():
                        d_str = idx.strftime("%Y-%m-%d")
                        bn_map[d_str] = brow

                yf_sessions = []
                for idx, nrow in n_df.tail(5).iterrows():
                    d_str = idx.strftime("%Y-%m-%d")
                    brow = bn_map.get(d_str)
                    o, h, l, c = float(nrow["Open"]), float(nrow["High"]), float(nrow["Low"]), float(nrow["Close"])
                    regime = "BULLISH_EXPANSION" if c > o + 50 else ("BEARISH_PRESSURE" if c < o - 50 else "BALANCED_ROTATION")
                    yf_sessions.append({
                        "date": d_str,
                        "regime": regime,
                        "nifty_open": round(o, 2),
                        "nifty_high": round(h, 2),
                        "nifty_low": round(l, 2),
                        "nifty_close": round(c, 2),
                        "banknifty_high": round(float(brow["High"]), 2) if brow is not None else None,
                        "banknifty_low": round(float(brow["Low"]), 2) if brow is not None else None,
                        "banknifty_close": round(float(brow["Close"]), 2) if brow is not None else None,
                        "fii_net_crores": None,
                        "dii_net_crores": None,
                        "oi_insight": "Derived from NSE daily cash auction extremes.",
                        "session_lesson": f"Range: {l:.1f} - {h:.1f}, Close: {c:.1f}",
                    })
                if yf_sessions:
                    return yf_sessions
        except Exception as e:
            logger.warning(f"Yahoo real multi-day session fetch failed: {e}")

        return sessions

    async def _seed_real_multi_day_history(self):
        """Populates rolling multi-day session history using real exchange daily OHLC."""
        sessions = await asyncio.to_thread(self._fetch_real_sessions_sync)
        if sessions:
            await redis_db.set_json(self.redis_key_sessions, sessions, expire=3600)
            fii_dii = await redis_db.get_json("FII_DII_DATA") or {}
            anchors = self._calculate_real_anchors(sessions, {}, fii_dii)
            await redis_db.set_json(self.redis_key_anchors, anchors, expire=3600)
            logger.info(f"Multi-Day Memory hydrated with {len(sessions)} real NSE trading sessions.")

    async def record_daily_session_close(self, session_data: Dict[str, Any]):
        """Appends completed trading session to rolling history."""
        try:
            raw_sessions = await redis_db.redis.get(self.redis_key_sessions)
            sessions = json.loads(raw_sessions) if raw_sessions else []
            sessions.append(session_data)
            sessions = sessions[-5:]
            await redis_db.set_json(self.redis_key_sessions, sessions)
            anchors = self._calculate_real_anchors(sessions)
            await redis_db.set_json(self.redis_key_anchors, anchors)
        except Exception as e:
            logger.error(f"Failed to record daily session: {e}")

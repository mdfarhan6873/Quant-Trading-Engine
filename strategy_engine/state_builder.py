import datetime
import json
import logging
import time
from collections import deque
from typing import Any, Dict, Optional
import pytz

from core.config import settings
from core.redis_client import redis_db
from strategy_engine.episodic_memory import QuantEpisodicMemoryRAG
from strategy_engine.multi_day_memory import MultiDayMemoryEngine

logger = logging.getLogger(__name__)

_upstox_holidays_cache = None


def is_market_open() -> bool:
    """Checks if Indian equity/derivatives markets are open (09:15 to 15:30 IST weekdays, excluding NSE holidays)."""
    global _upstox_holidays_cache

    tz = pytz.timezone("Asia/Kolkata")
    now = datetime.datetime.now(tz)

    if now.weekday() >= 5:
        return False

    market_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    if not (market_start <= now <= market_end):
        return False

    if _upstox_holidays_cache is None:
        try:
            import upstox_client
            api = upstox_client.MarketHolidaysAndTimingsApi()
            resp = api.get_holidays()
            _upstox_holidays_cache = []
            if getattr(resp, "data", None):
                for h in resp.data:
                    if "NSE" in getattr(h, "closed_exchanges", []):
                        _upstox_holidays_cache.append(h._date.date())
        except Exception as e:
            logger.debug(f"Upstox holidays check skipped: {e}")
            _upstox_holidays_cache = []

    if now.date() in _upstox_holidays_cache:
        return False

    return True


def get_analysis_window() -> str:
    """Returns scheduled pre/post market analysis window name if currently inside one."""
    tz = pytz.timezone("Asia/Kolkata")
    now = datetime.datetime.now(tz)

    if now.weekday() >= 5:
        return None
    if now.hour == 8 and 30 <= now.minute <= 59:
        return "PRE_MARKET_830"
    elif now.hour == 9 and now.minute == 14:
        return "PRE_MARKET_914"
    elif now.hour == 19 and 0 <= now.minute <= 5:
        return "POST_MARKET_1900"
    return None


class StateBuilder:
    """
    Aggregates real-time Redis / In-Memory market metrics across all 32 dimensions,
    pre-computes deterministic numeric deltas, and attaches Multi-Day Memory & Quant RAG precedents.
    Zero fake placeholder prices are injected anywhere.
    """

    def __init__(self):
        self.prev_state: Optional[Dict[str, Any]] = None
        self._history_snapshots: deque = deque(maxlen=60)
        self.memory_engine = MultiDayMemoryEngine()
        self.rag_engine = QuantEpisodicMemoryRAG()

    def _get_baseline_snapshot(self, now_ts: float, target_age_sec: float = 60.0) -> Optional[Dict[str, Any]]:
        """Finds a baseline state ~60s old for true 1-minute delta math, falling back to oldest usable snapshot."""
        if not self._history_snapshots:
            return self.prev_state

        best_snap = None
        best_diff = float("inf")
        for snap_ts, snap_state in self._history_snapshots:
            age = now_ts - snap_ts
            if 10.0 <= age <= 180.0:
                diff = abs(age - target_age_sec)
                if diff < best_diff:
                    best_diff = diff
                    best_snap = snap_state

        if best_snap is not None:
            return best_snap
        return self._history_snapshots[0][1] if self._history_snapshots else self.prev_state

    async def build_market_state_dict(self) -> Dict[str, Any]:
        """Builds the structured 32-dimension state dictionary from live feeds in Redis/memory."""
        try:
            # 1. Orderflow Metrics (PCR, CVD, VWAP, A/D Ratio)
            nifty_pcr_raw = await redis_db.redis.get("METRIC:PCR:NIFTY50")
            bank_pcr_raw = await redis_db.redis.get("METRIC:PCR:BANKNIFTY")
            nifty_pcr = float(json.loads(nifty_pcr_raw).get("pcr", 0.0)) if nifty_pcr_raw else 0.0
            bank_pcr = float(json.loads(bank_pcr_raw).get("pcr", 0.0)) if bank_pcr_raw else 0.0

            nifty_cvd_raw = await redis_db.redis.get("METRIC:CVD:NIFTY50")
            bank_cvd_raw = await redis_db.redis.get("METRIC:CVD:BANKNIFTY")
            nifty_cvd = int(json.loads(nifty_cvd_raw).get("cvd", 0)) if nifty_cvd_raw else 0
            bank_cvd = int(json.loads(bank_cvd_raw).get("cvd", 0)) if bank_cvd_raw else 0

            ad_ratio_raw = await redis_db.redis.get("METRIC:AD_RATIO")
            ad_data = json.loads(ad_ratio_raw) if ad_ratio_raw else {}
            ad_ratio = float(ad_data.get("ratio", 0.0)) if ad_data else 0.0

            nifty_vwap_raw = await redis_db.redis.get("METRIC:VWAP:NIFTY50")
            bank_vwap_raw = await redis_db.redis.get("METRIC:VWAP:BANKNIFTY")

            # 2. Greeks & Exposure
            nifty_gex = await redis_db.redis.get("METRIC:GEX:NIFTY")
            nifty_maxpain = await redis_db.redis.get("METRIC:MAX_PAIN:NIFTY")
            banknifty_gex = await redis_db.redis.get("METRIC:GEX:BANKNIFTY")
            banknifty_maxpain = await redis_db.redis.get("METRIC:MAX_PAIN:BANKNIFTY")

            nifty_gex_val = float(json.loads(nifty_gex).get("total_gex", 0.0)) if nifty_gex else 0.0
            nifty_maxpain_val = float(json.loads(nifty_maxpain).get("strike", 0.0)) if nifty_maxpain else 0.0
            banknifty_gex_val = float(json.loads(banknifty_gex).get("total_gex", 0.0)) if banknifty_gex else 0.0
            banknifty_maxpain_val = float(json.loads(banknifty_maxpain).get("strike", 0.0)) if banknifty_maxpain else 0.0

            # 3. Spot Indices, Futures, Volumes, VWAP & VIX
            nifty_spot_raw = await redis_db.redis.get("LTP:INDEX:NIFTY50")
            bank_spot_raw = await redis_db.redis.get("LTP:INDEX:NIFTYBANK")
            nifty_it_raw = await redis_db.redis.get("LTP:INDEX:NIFTYIT")
            vix_spot_raw = await redis_db.redis.get("LTP:INDEX:INDIAVIX")

            nifty_fut_raw = await redis_db.redis.get("LTP:FUT:NIFTY:CURR")
            bank_fut_raw = await redis_db.redis.get("LTP:FUT:BANKNIFTY:CURR")

            nifty_tick = json.loads(nifty_spot_raw) if nifty_spot_raw else {}
            bank_tick = json.loads(bank_spot_raw) if bank_spot_raw else {}
            nifty_it_tick = json.loads(nifty_it_raw) if nifty_it_raw else {}
            vix_tick = json.loads(vix_spot_raw) if vix_spot_raw else {}
            nifty_fut_tick = json.loads(nifty_fut_raw) if nifty_fut_raw else {}
            bank_fut_tick = json.loads(bank_fut_raw) if bank_fut_raw else {}

            nifty_spot = float(nifty_tick.get("ltp", 0.0) or 0.0)
            bank_spot = float(bank_tick.get("ltp", 0.0) or 0.0)
            it_spot = float(nifty_it_tick.get("ltp", 0.0) or 0.0)
            vix_spot = float(vix_tick.get("ltp", 0.0) or 0.0)

            nifty_vol = int(nifty_fut_tick.get("volume", 0) or 0)
            bank_vol = int(bank_fut_tick.get("volume", 0) or 0)
            it_vol = int(nifty_it_tick.get("volume", 0) or 0)

            nifty_fut = float(nifty_fut_tick.get("ltp", 0.0) or 0.0)
            bank_fut = float(bank_fut_tick.get("ltp", 0.0) or 0.0)

            nifty_premium = round(nifty_fut - nifty_spot, 2) if (nifty_spot > 0 and nifty_fut > 0) else 0.0
            bank_premium = round(bank_fut - bank_spot, 2) if (bank_spot > 0 and bank_fut > 0) else 0.0

            nifty_vwap = float(json.loads(nifty_vwap_raw).get("vwap", 0.0)) if nifty_vwap_raw else float(nifty_fut_tick.get("vwap", 0.0) or 0.0)
            if nifty_vwap <= 0:
                nifty_vwap = nifty_fut or nifty_spot

            bank_vwap = float(json.loads(bank_vwap_raw).get("vwap", 0.0)) if bank_vwap_raw else float(bank_fut_tick.get("vwap", 0.0) or 0.0)
            if bank_vwap <= 0:
                bank_vwap = bank_fut or bank_spot

            now_ts = time.time()
            baseline = self._get_baseline_snapshot(now_ts, target_age_sec=60.0)

            nifty_dist_vwap = round(nifty_spot - nifty_vwap, 2) if (nifty_spot > 0 and nifty_vwap > 0) else 0.0
            bank_dist_vwap = round(bank_spot - bank_vwap, 2) if (bank_spot > 0 and bank_vwap > 0) else 0.0

            nifty_delta_vol = 0
            bank_delta_vol = 0
            it_delta_vol = 0
            nifty_delta_price = 0.0
            bank_delta_price = 0.0
            it_delta_price = 0.0
            nifty_delta_dist_vwap = 0.0
            bank_delta_dist_vwap = 0.0
            vix_delta = float(vix_tick.get("change", 0.0) or 0.0)
            vix_delta_1m = 0.0
            nifty_delta_cvd_1m = 0
            bank_delta_cvd_1m = 0

            if baseline:
                prev_ind = baseline.get("indices", {})
                prev_n = prev_ind.get("NIFTY50", {})
                prev_b = prev_ind.get("BANKNIFTY", {})
                prev_it = prev_ind.get("NIFTYIT", {})
                prev_vix = prev_ind.get("INDIAVIX", {})
                prev_of = baseline.get("orderflow", {})

                if prev_n.get("volume"):
                    nifty_delta_vol = nifty_vol - int(prev_n.get("volume") or nifty_vol)
                if prev_b.get("volume"):
                    bank_delta_vol = bank_vol - int(prev_b.get("volume") or bank_vol)
                if prev_it.get("volume"):
                    it_delta_vol = it_vol - int(prev_it.get("volume") or it_vol)
                if prev_n.get("ltp") and nifty_spot > 0:
                    nifty_delta_price = round(nifty_spot - float(prev_n["ltp"]), 2)
                if prev_b.get("ltp") and bank_spot > 0:
                    bank_delta_price = round(bank_spot - float(prev_b["ltp"]), 2)
                if prev_it.get("ltp") and it_spot > 0:
                    it_delta_price = round(it_spot - float(prev_it["ltp"]), 2)
                if prev_vix.get("ltp") and vix_spot > 0:
                    vix_delta_1m = round(vix_spot - float(prev_vix["ltp"]), 2)
                if prev_n.get("dist_to_vwap") is not None:
                    nifty_delta_dist_vwap = round(nifty_dist_vwap - float(prev_n.get("dist_to_vwap") or 0.0), 2)
                if prev_b.get("dist_to_vwap") is not None:
                    bank_delta_dist_vwap = round(bank_dist_vwap - float(prev_b.get("dist_to_vwap") or 0.0), 2)
                if prev_of.get("NIFTY_CVD") is not None:
                    nifty_delta_cvd_1m = nifty_cvd - int(prev_of.get("NIFTY_CVD") or 0)
                if prev_of.get("BANKNIFTY_CVD") is not None:
                    bank_delta_cvd_1m = bank_cvd - int(prev_of.get("BANKNIFTY_CVD") or 0)

            # 4. Macro Context
            macro_state_raw = await redis_db.redis.get("MACRO_STATE")
            macro_state = json.loads(macro_state_raw) if macro_state_raw else {}

            # 5. Heavyweight Equities (Top 27 drivers)
            heavyweight_symbols = [
                "HDFCBANK", "RELIANCE", "ICICIBANK", "INFY", "ITC",
                "TCS", "LT", "AXISBANK", "KOTAKBANK", "SBIN",
                "BHARTIARTL", "HINDUNILVR", "BAJFINANCE", "MARUTI", "M&M",
                "HCLTECH", "TMPV", "SUNPHARMA", "ONGC", "NTPC",
                "POWERGRID", "TITAN", "ULTRACEMCO", "COALINDIA",
                "INDUSINDBK", "PNB", "BANKBARODA",
            ]
            heavyweights = {}
            for sym in heavyweight_symbols:
                tick_raw = await redis_db.redis.get(f"LTP:EQ:{sym}")
                if tick_raw:
                    tick = json.loads(tick_raw)
                    imb_raw = await redis_db.redis.get(f"METRIC:IMBALANCE:EQ:{sym}")
                    imb = float(json.loads(imb_raw).get("ratio", tick.get("imbalance", 1.0))) if imb_raw else float(tick.get("imbalance", 1.0))
                    vol = int(tick.get("volume", 0) or 0)
                    delta_vol = 0
                    if baseline:
                        prev_h = baseline.get("heavyweights", {}).get(sym, {})
                        if prev_h.get("volume"):
                            delta_vol = vol - int(prev_h.get("volume") or vol)

                    hw_ltp = float(tick.get("ltp", 0.0) or 0.0)
                    hw_close = float(tick.get("close", 0.0) or 0.0)
                    raw_dc = tick.get("day_change")
                    if raw_dc is None:
                        raw_dc = tick.get("change")
                    hw_dc = float(raw_dc) if raw_dc is not None else (hw_ltp - hw_close if (hw_ltp > 0 and hw_close > 0) else 0.0)
                    raw_dcp = tick.get("day_change_pct")
                    if raw_dcp is None:
                        raw_dcp = tick.get("pct_change")
                    hw_dcp = (
                        float(raw_dcp)
                        if raw_dcp is not None
                        else (((hw_ltp - hw_close) / hw_close) * 100.0 if (hw_ltp > 0 and hw_close > 0) else 0.0)
                    )

                    heavyweights[sym] = {
                        "ltp": hw_ltp,
                        "close": hw_close,
                        "day_change": round(hw_dc, 2),
                        "day_change_pct": round(hw_dcp, 2),
                        "volume": vol,
                        "delta_volume": delta_vol,
                        "imbalance": round(imb, 2),
                        "source": tick.get("source", "live"),
                    }

            # 6. Portfolio Positions
            paper_positions_raw = await redis_db.redis.get("PAPER_POSITIONS")
            portfolio = json.loads(paper_positions_raw) if paper_positions_raw else {}

            # 6.5 Institutional FII/DII & Real Prev Day OHLC
            fii_dii_raw = await redis_db.redis.get("FII_DII_DATA")
            fii_dii = json.loads(fii_dii_raw) if fii_dii_raw else {}
            if fii_dii and "fii_cash" in fii_dii and "fii_net_crores" not in fii_dii:
                fii_dii["fii_net_crores"] = fii_dii["fii_cash"]
            if fii_dii and "dii_cash" in fii_dii and "dii_net_crores" not in fii_dii:
                fii_dii["dii_net_crores"] = fii_dii["dii_cash"]

            prev_ohlc_raw = await redis_db.redis.get("PREV_DAY_OHLC")
            prev_ohlc = json.loads(prev_ohlc_raw) if prev_ohlc_raw else {
                "NIFTY50": {
                    "close": float(nifty_tick.get("close", 0.0) or 0.0),
                    "pdh": float(nifty_tick.get("high", 0.0) or 0.0),
                    "pdl": float(nifty_tick.get("low", 0.0) or 0.0),
                },
                "BANKNIFTY": {
                    "close": float(bank_tick.get("close", 0.0) or 0.0),
                    "pdh": float(bank_tick.get("high", 0.0) or 0.0),
                    "pdl": float(bank_tick.get("low", 0.0) or 0.0),
                },
            }

            tz = pytz.timezone("Asia/Kolkata")
            market_time = datetime.datetime.now(tz).strftime("%H:%M:%S")
            market_open = is_market_open()

            # 7. Option Chain (ATM ± 20 Strikes)
            option_chain: Dict[str, Dict[str, Any]] = {"NIFTY": {}, "BANKNIFTY": {}}

            for idx_name, spot_val, step in (("NIFTY", nifty_spot, 50), ("BANKNIFTY", bank_spot, 100)):
                if spot_val <= 0:
                    continue
                atm = int(round(spot_val / float(step))) * step
                for offset in range(-20, 21):
                    strike = atm + (offset * step)
                    for opt_type in ("CE", "PE"):
                        sym = f"OPT:{idx_name}:{strike}{opt_type}"
                        tick_raw = await redis_db.redis.get(f"LTP:{sym}")
                        if not tick_raw:
                            continue
                        tick = json.loads(tick_raw)
                        vol = int(tick.get("volume", 0) or 0)
                        oi = int(tick.get("oi", 0) or 0)

                        # Preserve exchange-reported intraday Change in OI if available!
                        ltp_val = float(tick.get("ltp", 0.0) or 0.0)
                        delta_oi = int(tick.get("delta_oi", 0) or 0)
                        delta_vol = int(tick.get("delta_volume", 0) or 0)
                        delta_ltp_1m = 0.0
                        if baseline:
                            prev_opt = (
                                baseline.get("options_data", {})
                                .get("chain", {})
                                .get(idx_name, {})
                                .get(f"{strike}{opt_type}", {})
                            )
                            if prev_opt.get("volume"):
                                delta_vol = vol - int(prev_opt.get("volume") or vol)
                            if delta_oi == 0 and prev_opt.get("oi"):
                                delta_oi = oi - int(prev_opt.get("oi") or oi)
                            if prev_opt.get("ltp") and ltp_val > 0:
                                delta_ltp_1m = round(ltp_val - float(prev_opt["ltp"]), 2)

                        greek_raw = await redis_db.redis.get(f"GREEKS:{sym}")
                        greek_data = json.loads(greek_raw) if greek_raw else {}

                        option_chain[idx_name][f"{strike}{opt_type}"] = {
                            "ltp": ltp_val,
                            "delta_ltp_1m": delta_ltp_1m,
                            "volume": vol,
                            "delta_volume": delta_vol,
                            "oi": oi,
                            "delta_oi": delta_oi,
                            "iv": float(greek_data.get("iv", tick.get("iv", 0.0)) or 0.0),
                            "delta": float(greek_data.get("delta", tick.get("delta", 0.0)) or 0.0),
                            "gamma": float(greek_data.get("gamma", tick.get("gamma", 0.0)) or 0.0),
                            "theta": float(greek_data.get("theta", tick.get("theta", 0.0)) or 0.0),
                            "vega": float(greek_data.get("vega", tick.get("vega", 0.0)) or 0.0),
                            "rho": float(greek_data.get("rho", tick.get("rho", 0.0)) or 0.0),
                            "bid": float(tick.get("bid", 0.0) or 0.0),
                            "ask": float(tick.get("ask", 0.0) or 0.0),
                            "tbq": int(tick.get("tbq", 0) or 0),
                            "tsq": int(tick.get("tsq", 0) or 0),
                            "bid_ask_spread": float(tick.get("bid_ask_spread", 0.0) or 0.0),
                        }

            # Feed/Telemetry source summary
            upstox_status = await redis_db.get_json("SYSTEM:UPSTOX_STATUS") or {"connected": False, "token_valid": False}
            feed_status = await redis_db.get_json("SYSTEM:FEED_STATUS") or {}
            llm_status = await redis_db.get_json("SYSTEM:LLM_STATUS") or {}
            analysis_raw = await redis_db.redis.get("LATEST_MARKET_ANALYSIS")
            latest_analysis = json.loads(analysis_raw) if analysis_raw else []

            multi_day_memory = await self.memory_engine.get_multi_day_context()

            state: Dict[str, Any] = {
                "market_time": market_time,
                "timestamp": now_ts,
                "is_market_open": market_open,
                "analysis_window": get_analysis_window(),
                "latest_analysis_context": latest_analysis,
                "multi_day_memory": multi_day_memory,
                "data_sources": {
                    "redis_connected": redis_db.is_connected,
                    "upstox_ws": upstox_status,
                    "live_poller": feed_status.get("primary_feed", "NSE_OFFICIAL + GROWW + YAHOO"),
                    "last_poll_ts": feed_status.get("last_poll_ts"),
                    "nifty_source": nifty_tick.get("source", "offline"),
                    "vix_source": vix_tick.get("source", "offline"),
                    "llm_status": llm_status,
                },
                "indices": {
                    "NIFTY50": {
                        "ltp": nifty_spot,
                        "open": float(nifty_tick.get("open", 0.0) or 0.0),
                        "high": float(nifty_tick.get("high", 0.0) or 0.0),
                        "low": float(nifty_tick.get("low", 0.0) or 0.0),
                        "prev_close": float(nifty_tick.get("close", 0.0) or 0.0),
                        "day_change": float(nifty_tick.get("change", 0.0) or 0.0),
                        "day_change_pct": float(nifty_tick.get("pct_change", 0.0) or 0.0),
                        "delta_price_1m": nifty_delta_price,
                        "volume": nifty_vol,
                        "delta_volume": nifty_delta_vol,
                        "vwap": round(nifty_vwap, 2),
                        "dist_to_vwap": nifty_dist_vwap,
                        "delta_dist_to_vwap": nifty_delta_dist_vwap,
                        "futures_ltp": round(nifty_fut, 2),
                        "futures_premium": nifty_premium,
                        "source": nifty_tick.get("source", "offline"),
                    },
                    "BANKNIFTY": {
                        "ltp": bank_spot,
                        "open": float(bank_tick.get("open", 0.0) or 0.0),
                        "high": float(bank_tick.get("high", 0.0) or 0.0),
                        "low": float(bank_tick.get("low", 0.0) or 0.0),
                        "prev_close": float(bank_tick.get("close", 0.0) or 0.0),
                        "day_change": float(bank_tick.get("change", 0.0) or 0.0),
                        "day_change_pct": float(bank_tick.get("pct_change", 0.0) or 0.0),
                        "delta_price_1m": bank_delta_price,
                        "volume": bank_vol,
                        "delta_volume": bank_delta_vol,
                        "vwap": round(bank_vwap, 2),
                        "dist_to_vwap": bank_dist_vwap,
                        "delta_dist_to_vwap": bank_delta_dist_vwap,
                        "futures_ltp": round(bank_fut, 2),
                        "futures_premium": bank_premium,
                        "source": bank_tick.get("source", "offline"),
                    },
                    "NIFTYIT": {
                        "ltp": it_spot,
                        "prev_close": float(nifty_it_tick.get("close", 0.0) or 0.0),
                        "day_change": float(nifty_it_tick.get("change", 0.0) or 0.0),
                        "day_change_pct": float(nifty_it_tick.get("pct_change", 0.0) or 0.0),
                        "delta_price_1m": it_delta_price,
                        "volume": it_vol,
                        "delta_volume": it_delta_vol,
                        "source": nifty_it_tick.get("source", "offline"),
                    },
                    "INDIAVIX": {
                        "ltp": vix_spot,
                        "prev_close": float(vix_tick.get("close", 0.0) or 0.0),
                        "delta_vix": vix_delta,
                        "delta_vix_1m": vix_delta_1m,
                        "pct_change": float(vix_tick.get("pct_change", 0.0) or 0.0),
                        "open": float(vix_tick.get("open", 0.0) or 0.0),
                        "high": float(vix_tick.get("high", 0.0) or 0.0),
                        "low": float(vix_tick.get("low", 0.0) or 0.0),
                        "source": vix_tick.get("source", "offline"),
                    },
                },
                "orderflow": {
                    "NIFTY_PCR": nifty_pcr,
                    "BANKNIFTY_PCR": bank_pcr,
                    "NIFTY_CVD": nifty_cvd,
                    "delta_nifty_cvd_1m": nifty_delta_cvd_1m,
                    "BANKNIFTY_CVD": bank_cvd,
                    "delta_banknifty_cvd_1m": bank_delta_cvd_1m,
                    "AD_RATIO": ad_ratio,
                    "AD_ADVANCES": ad_data.get("advances"),
                    "AD_DECLINES": ad_data.get("declines"),
                },
                "options_data": {
                    "NIFTY_GEX": float(nifty_gex_val),
                    "NIFTY_MAXPAIN": float(nifty_maxpain_val),
                    "BANKNIFTY_GEX": float(banknifty_gex_val),
                    "BANKNIFTY_MAXPAIN": float(banknifty_maxpain_val),
                    "chain": option_chain,
                },
                "heavyweights": heavyweights,
                "macro": macro_state.get("markets", {}),
                "institutional": fii_dii,
                "prev_ohlc": prev_ohlc,
                "breaking_news": macro_state.get("news", {}).get("global_breaking", []),
                "indian_news": macro_state.get("news", {}).get("indian_markets", []),
                "portfolio": portfolio,
            }

            rag_context = self.rag_engine.search_similar_regimes(state)
            state["quant_rag_context"] = rag_context
            self.prev_state = state
            self._history_snapshots.append((now_ts, state))
            return state
        except Exception as e:
            logger.error(f"Failed to build market state: {e}")
            return {}

    async def build_market_state(self) -> str:
        """Builds compact JSON string for FULL_MARKET_STATE Redis persistence."""
        state = await self.build_market_state_dict()
        if not state:
            return "{}"
        return json.dumps(state, separators=(",", ":"))

    def _compress_option_chain_for_llm(self, state_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Selects ATM+-2 core contracts (full Greeks) plus top 3 CE/PE OI walls to keep LLM latency fast."""
        indices = state_dict.get("indices", {})
        raw_chain = state_dict.get("options_data", {}).get("chain", {})
        compressed = {}

        for idx_name, spot_key, step in (("NIFTY", "NIFTY50", 50), ("BANKNIFTY", "BANKNIFTY", 100)):
            spot = float(indices.get(spot_key, {}).get("ltp", 0.0) or 0.0)
            idx_chain = raw_chain.get(idx_name, {})
            if spot <= 0 or not idx_chain:
                compressed[idx_name] = {"tier1_atm_core": {}, "tier2_oi_walls": {}}
                continue
            atm = int(round(spot / float(step))) * step
            core_strikes = {f"{atm + i * step}{t}" for i in range(-2, 3) for t in ("CE", "PE")}
            tier1 = {}
            ce_wings = []
            pe_wings = []
            for contract, metrics in idx_chain.items():
                if contract in core_strikes:
                    tier1[contract] = metrics
                else:
                    compact = {
                        "ltp": metrics.get("ltp", 0.0),
                        "oi": metrics.get("oi", 0),
                        "delta_oi": metrics.get("delta_oi", 0),
                        "iv": metrics.get("iv", 0.0),
                    }
                    if contract.endswith("CE"):
                        ce_wings.append((int(metrics.get("oi", 0) or 0), contract, compact))
                    else:
                        pe_wings.append((int(metrics.get("oi", 0) or 0), contract, compact))
            ce_wings.sort(key=lambda x: x[0], reverse=True)
            pe_wings.sort(key=lambda x: x[0], reverse=True)
            tier2 = {c: m for _, c, m in (ce_wings[:3] + pe_wings[:3])}
            compressed[idx_name] = {"tier1_atm_core": tier1, "tier2_oi_walls": tier2}
        return compressed

    def build_tripartite_llm_payload(
        self,
        state_dict: Dict[str, Any],
        previous_decision: Optional[Dict[str, Any]] = None,
        execution_state: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Builds the token-optimized Tripartite Request JSON envelope (Parts A, B, C, D) matching Contract Spec §2.4-2.7."""
        top_heavyweights = {
            k: {
                "ltp": v.get("ltp"),
                "chg_pct": v.get("day_change_pct"),
                "imb": v.get("imbalance"),
            }
            for k, v in list((state_dict.get("heavyweights") or {}).items())[:8]
        }

        def _compact_news(items: Any, limit: int) -> list:
            out = []
            for it in (items or [])[:limit]:
                if isinstance(it, dict):
                    out.append({"title": it.get("title") or it.get("headline"), "sentiment": it.get("sentiment")})
                else:
                    out.append(str(it)[:140])
            return out

        compact_prev = {"status": "INITIAL_BASELINE", "action": "OBSERVE", "reason": "No prior decision recorded in Redis yet."}
        if isinstance(previous_decision, dict) and previous_decision:
            compact_prev = {
                "decision_id": previous_decision.get("decision_id"),
                "timestamp": previous_decision.get("timestamp"),
                "action": previous_decision.get("action"),
                "direction": previous_decision.get("direction"),
                "setup": previous_decision.get("setup"),
                "symbol": previous_decision.get("symbol"),
                "confidence": previous_decision.get("confidence"),
                "reason": previous_decision.get("reason"),
                "summary_metrics": (previous_decision.get("factor_audit") or {}).get("summary_metrics"),
            }

        market_part_b = {
            "market_time": state_dict.get("market_time"),
            "timestamp": state_dict.get("timestamp"),
            "is_market_open": state_dict.get("is_market_open"),
            "analysis_window": state_dict.get("analysis_window"),
            "indices": state_dict.get("indices", {}),
            "orderflow": state_dict.get("orderflow", {}),
            "options_exposure": {
                "NIFTY_GEX": state_dict.get("options_data", {}).get("NIFTY_GEX", 0.0),
                "NIFTY_MAXPAIN": state_dict.get("options_data", {}).get("NIFTY_MAXPAIN", 0.0),
                "BANKNIFTY_GEX": state_dict.get("options_data", {}).get("BANKNIFTY_GEX", 0.0),
                "BANKNIFTY_MAXPAIN": state_dict.get("options_data", {}).get("BANKNIFTY_MAXPAIN", 0.0),
                "chain": self._compress_option_chain_for_llm(state_dict),
            },
            "heavyweights_top8": top_heavyweights,
            "macro": state_dict.get("macro", {}),
            "institutional": state_dict.get("institutional", {}),
            "prev_ohlc": state_dict.get("prev_ohlc", {}),
            "multi_day_memory": state_dict.get("multi_day_memory", {}),
            "quant_rag_context": state_dict.get("quant_rag_context", {}),
            "indian_news": _compact_news(state_dict.get("indian_news"), 4),
            "breaking_news": _compact_news(state_dict.get("breaking_news"), 3),
        }

        payload = {
            "part_a_previous_decision": compact_prev,
            "part_b_current_market_state": market_part_b,
            "part_c_current_execution_state": execution_state
            or {
                "open_positions": state_dict.get("portfolio", {}),
                "capital_available": getattr(settings, "MAX_CAPITAL", 50000),
                "trades_executed_today": 0,
                "max_daily_trades": 3,
                "cooldown_remaining_seconds": 0,
            },
            "part_d_cognitive_instructions": {
                "continuity_rule": "Cite exact regime shift or metric delta vs part_a_previous_decision before altering conviction or action.",
                "audit_rule": "Audit all 32 market dimensions in factor_audit (available/conflicting/unavailable) before emitting a decision.",
                "patience_rule": "The 60s re-evaluation loop is an audit heartbeat, not an obligation to trade. Default to OBSERVE or HOLD unless >90% alignment holds.",
            },
        }
        return json.dumps(payload, separators=(",", ":"))

    async def get_system_prompt(self, is_open: bool = True, analysis_window: str = None) -> str:
        """Returns the system prompt instructing the LLM on market regime, patience rules, and Contract 1 schema."""
        if analysis_window:
            return (
                f"You are an elite quantitative macro-analyst AI specializing in Indian Markets (Nifty/BankNifty). "
                f"The current market phase is {analysis_window}. Analyze FII/DII data, global macro indices, breaking news, heavyweights, and option chain positioning (GEX/MaxPain). "
                "Output EXACTLY one valid JSON object matching this schema with NO markdown fences:\n"
                '{"decision_id":"DEC_PREMARKET","action":"ANALYSIS","direction":"NEUTRAL","setup":"PRE_MARKET_PREP","symbol":"MACRO","lots":0,"confidence":100,"reason":"<detailed quantitative analysis>"}'
            )
        elif not is_open:
            return (
                "You are an elite quantitative macro-analyst AI specializing in Indian Markets (Nifty/BankNifty). "
                "The market is currently CLOSED. Analyze post-market/pre-market data in the state JSON (FII/DII, global macros, GIFT Nifty, news, heavyweights, option positioning) to form a bias for tomorrow. "
                "Output EXACTLY one valid JSON object with NO markdown fences:\n"
                '{"decision_id":"DEC_AFTERHOURS","action":"ANALYSIS","direction":"NEUTRAL","setup":"POST_MARKET_REVIEW","symbol":"MARKET_CLOSED","lots":0,"confidence":85,"reason":"<high-impact analytical narrative summarizing key drivers for tomorrow>"}'
            )

        min_conf = 90 if str(getattr(settings, "TRADING_MODE", "PAPER")).upper() == "LIVE" else max(70, int(getattr(settings, "LLM_MIN_CONFIDENCE", 78) or 78))
        return (
            "You are an elite institutional quantitative reasoning engine specializing in Indian Index Options (Nifty 50 and Bank Nifty).\n"
            "CORE DIRECTIVE: Discipline != Paralysis. Stay 'OBSERVE' during directionless range/chop around VWAP, "
            f"and ACT decisively with ENTER_CALL or ENTER_PUT (1-3 high-conviction trades/day) whenever directional alignment reaches >= {min_conf}%.\n"
            "INDIAN MARKET CALIBRATION:\n"
            "- Monthly Nifty/BankNifty Futures carry ~0.35%-0.45% (~90-125 pts) baseline cost-of-carry; treat tightening/widening basis change as the signal, NOT raw positive points as bullish.\n"
            "- Yesterday's EOD FII cash (`FII_DII_DATA`) is a lagging contextual factor (`critical: false`): NEVER veto a live -0.6%+ intraday breakdown solely because yesterday's FII figure was net positive.\n"
            "- Orderly trend breakdowns/breakouts often occur with flat/drifting VIX (`14-18`). Strong Spot vs VWAP + PDL/PDH break + broad Heavyweight alignment + negative/positive CVD + skewed A/D (<0.45 or >2.0) is sufficient for conviction >= 80%.\n"
            "- When triggering ENTER_CALL or ENTER_PUT, set `symbol` to the nearest liquid ATM contract e.g. `OPT:NIFTY:<ATM_STRIKE>PE` or `OPT:NIFTY:<ATM_STRIKE>CE` and `lots` >= 1.\n"
            "RULE 1 (CONTINUITY): Compare part_b_current_market_state against part_a_previous_decision and state what changed.\n"
            "RULE 2 (CONTRACT 1 JSON): Output STRICTLY ONE valid JSON object (no markdown fences) with these keys:\n"
            '{"decision_id":"DEC_<HHMMSS>","timestamp":"<IST_ISO>","instrument":"NIFTY50|BANKNIFTY","timeframe":"1m",'
            '"action":"OBSERVE|ENTER_CALL|ENTER_PUT|HOLD|EXIT|NO_TRADE|REDUCE|CLOSE_ALL",'
            '"direction":"BULLISH|BEARISH|NEUTRAL","setup":"<setup_tag>","symbol":"<OPT:NIFTY:25600PE or empty>",'
            '"lots":<int>,"confidence":<0-100>,'
            '"reason":"<concise institutional synthesis citing spot, vwap, futures delta, pcr, cvd, heavyweights, gex, vix, and delta vs prev decision>",'
            '"factor_audit":{"summary_metrics":{"total_factors_evaluated":32,"available_count":<int>,"conflicting_count":<int>,"unavailable_count":<int>,"bullish_count":<int>,"bearish_count":<int>,"neutral_count":<int>,"critical_failures":<int>},'
            '"factors":[{"id":1,"name":"Nifty Spot","category":"Spot & Futures","status":"AVAILABLE|CONFLICTING|UNAVAILABLE","value":"<str>","evidence":"BULLISH|BEARISH|NEUTRAL|MISSING","critical":true},...]}}\n'
            "Include the top 8-10 decisive factors in factor_audit.factors covering Spot, Futures Basis, VWAP, ATM Options/OI/Greeks, PCR/CVD/A-D, GEX/VIX, Heavyweights, Macro/FII-DII, Multi-Day Anchors, and Quant RAG while counting all 32 evaluated dimensions in summary_metrics. Mark lagging/secondary macro cues `critical: false`."
        )

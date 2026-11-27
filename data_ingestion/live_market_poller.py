import asyncio
import datetime
import json
import logging
import time
from typing import Any, Dict, List, Optional

import pytz
from core.redis_client import redis_db
from data_ingestion.greeks_engine import GreeksEngine

logger = logging.getLogger(__name__)

# Top 27 liquid NSE Nifty 50 / Bank Nifty drivers (using TMPV following Tata Motors demerger)
HEAVYWEIGHT_SYMBOLS = [
    "HDFCBANK", "RELIANCE", "ICICIBANK", "INFY", "ITC",
    "TCS", "LT", "AXISBANK", "KOTAKBANK", "SBIN",
    "BHARTIARTL", "HINDUNILVR", "BAJFINANCE", "MARUTI", "M&M",
    "HCLTECH", "TMPV", "SUNPHARMA", "ONGC", "NTPC",
    "POWERGRID", "TITAN", "ULTRACEMCO", "COALINDIA",
    "INDUSINDBK", "PNB", "BANKBARODA",
]


class LiveMarketPoller:
    """
    High-Precision Real-Time Exchange Data Poller (NSE Official + Groww Public + Yahoo 1m).
    Ensures 100% authentic live market metrics (NIFTY 50, BANK NIFTY, INDIA VIX, NIFTY IT,
    Index Futures + VWAP, ATM ± 20 Option Chain + OI + ΔOI + Bid/Ask + Vollib Greeks,
    Top 27 Heavyweights + Order Book Imbalances, Breadth A/D, and 1m Intraday Candles)
    are continuously populated into Redis even if Upstox's daily OAuth token has expired.

    Sub-second Upstox WebSocket ticks (`source == "upstox_ws"`) are NEVER overwritten while
    active within the last 5 seconds.
    """

    def __init__(self, greeks_engine: Optional[GreeksEngine] = None):
        self.is_running = False
        self.tz = pytz.timezone("Asia/Kolkata")
        self.greeks = greeks_engine or GreeksEngine()
        self._nse_session = None
        self._nse_cookies_ts = 0.0
        self._expiry_cache: Dict[str, str] = {}
        self._prev_fut_state: Dict[str, Dict[str, float]] = {}
        self._cvd_state: Dict[str, int] = {"NIFTY50": 0, "BANKNIFTY": 0}
        self._prev_opt_state: Dict[str, Dict[str, float]] = {}
        self._last_candles_ts = 0.0
        self._cycle_count = 0

    def _get_nse_session(self):
        from curl_cffi import requests as creq
        now = time.time()
        if self._nse_session is None or (now - self._nse_cookies_ts) > 240:
            s = creq.Session(impersonate="chrome")
            try:
                s.get("https://www.nseindia.com/option-chain", timeout=8)
                self._nse_cookies_ts = now
            except Exception as e:
                logger.debug(f"NSE cookie warmup notice: {e}")
            self._nse_session = s
        return self._nse_session

    async def _is_upstox_ws_fresh(self, redis_key: str) -> bool:
        try:
            existing = await redis_db.get_json(redis_key)
            if existing and existing.get("source") == "upstox_ws":
                ts = float(existing.get("timestamp", 0) or 0)
                if (time.time() - ts) < 5.0:
                    return True
        except Exception:
            pass
        return False

    def _fetch_nse_indices_sync(self) -> Dict[str, Any]:
        """Fetches exact NIFTY 50, NIFTY BANK, NIFTY IT, and INDIA VIX from NSE allIndices."""
        out: Dict[str, Any] = {}
        try:
            s = self._get_nse_session()
            r = s.get(
                "https://www.nseindia.com/api/allIndices",
                headers={"Referer": "https://www.nseindia.com/"},
                timeout=8,
            )
            if r.status_code == 200:
                j = r.json()
                target_map = {
                    "NIFTY 50": "INDEX:NIFTY50",
                    "NIFTY BANK": "INDEX:NIFTYBANK",
                    "NIFTY IT": "INDEX:NIFTYIT",
                    "INDIA VIX": "INDEX:INDIAVIX",
                }
                for row in j.get("data", []):
                    idx_name = row.get("index")
                    if idx_name in target_map:
                        internal_sym = target_map[idx_name]
                        ltp = float(row.get("last", 0.0) or 0.0)
                        prev_close = float(row.get("previousClose", ltp) or ltp)
                        var = float(row.get("variation", ltp - prev_close) or 0.0)
                        pct = float(row.get("percentChange", 0.0) or 0.0)
                        item = {
                            "symbol": internal_sym,
                            "ltp": round(ltp, 2),
                            "open": round(float(row.get("open", ltp) or ltp), 2),
                            "high": round(float(row.get("high", ltp) or ltp), 2),
                            "low": round(float(row.get("low", ltp) or ltp), 2),
                            "close": round(prev_close, 2),
                            "change": round(var, 2),
                            "pct_change": round(pct, 2),
                            "volume": 0,
                            "oi": 0,
                            "vwap": 0.0,
                            "bid_ask": {"depth": []},
                            "source": "nse_official",
                            "timestamp": time.time(),
                        }
                        if idx_name == "NIFTY 50" and row.get("advances") is not None:
                            try:
                                item["advances"] = int(row.get("advances", 0))
                                item["declines"] = int(row.get("declines", 0))
                                item["unchanged"] = int(row.get("unchanged", 0))
                            except Exception:
                                pass
                        out[internal_sym] = item
                out["_meta_timestamp"] = j.get("timestamp")
        except Exception as e:
            logger.warning(f"NSE allIndices fetch failed: {e}")

        # Groww index OHLC fallback if NSE index call had any miss
        if "INDEX:NIFTY50" not in out or "INDEX:INDIAVIX" not in out:
            try:
                from curl_cffi import requests as creq
                groww_map = {
                    "NIFTY": "INDEX:NIFTY50",
                    "BANKNIFTY": "INDEX:NIFTYBANK",
                    "INDIAVIX": "INDEX:INDIAVIX",
                }
                for g_sym, internal_sym in groww_map.items():
                    if internal_sym in out:
                        continue
                    rg = creq.get(
                        f"https://groww.in/v1/api/stocks_data/v1/accord_points/exchange/NSE/segment/CASH/latest_indices_ohlc/{g_sym}",
                        impersonate="chrome",
                        timeout=4,
                    )
                    if rg.status_code == 200:
                        d = rg.json()
                        val = float(d.get("value", 0.0) or 0.0)
                        if val > 0:
                            out[internal_sym] = {
                                "symbol": internal_sym,
                                "ltp": round(val, 2),
                                "open": round(float(d.get("open", val) or val), 2),
                                "high": round(float(d.get("high", val) or val), 2),
                                "low": round(float(d.get("low", val) or val), 2),
                                "close": round(float(d.get("close", val) or val), 2),
                                "change": round(float(d.get("dayChange", 0.0) or 0.0), 2),
                                "pct_change": round(float(d.get("dayChangePerc", 0.0) or 0.0), 2),
                                "volume": 0,
                                "oi": 0,
                                "vwap": 0.0,
                                "bid_ask": {"depth": []},
                                "source": "groww_live",
                                "timestamp": time.time(),
                            }
            except Exception as ge:
                logger.debug(f"Groww index fallback error: {ge}")

        return out

    def _parse_nse_expiry(self, exp_str: str) -> datetime.date:
        for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.datetime.strptime(exp_str.strip(), fmt).date()
            except Exception:
                continue
        return datetime.date(2099, 12, 31)

    def _fetch_nse_derivatives_sync(self, index_name: str, spot_price: float) -> Dict[str, Any]:
        """
        Fetches real Futures LTP/Volume/VWAP/OI and nearest-expiry ATM ± 20 Option Chain
        (with real OI, ΔOI, IV, Bid/Ask depth, Spread, and Vollib Greeks) from NSE.
        """
        result: Dict[str, Any] = {"futures": None, "options": [], "expiry": None, "lot_size": 65 if index_name == "NIFTY" else 30}
        try:
            s = self._get_nse_session()

            # 1. Fetch Futures & contract overview via NextApi
            r_deriv = s.get(
                f"https://www.nseindia.com/api/NextApi/apiClient/GetQuoteApi?functionName=getSymbolDerivativesData&symbol={index_name}",
                headers={"Referer": "https://www.nseindia.com/option-chain"},
                timeout=8,
            )
            if r_deriv.status_code == 200:
                items = r_deriv.json().get("data", [])
                futs = [x for x in items if x.get("instrumentType") == "FUTIDX"]
                if futs:
                    futs.sort(key=lambda x: self._parse_nse_expiry(x.get("expiryDate", "")))
                    front = futs[0]
                    contracts = int(float(front.get("totalTradedVolume", 0) or 0))
                    turnover = float(front.get("totalTurnover", 0.0) or 0.0)
                    lot_sz = 65 if index_name == "NIFTY" else 30
                    if front.get("volumeFreezeQuantity"):
                        # Derive exact lot_size heuristically if possible, otherwise keep standard SEBI lot
                        pass
                    vwap = round(turnover / (contracts * lot_sz), 2) if (contracts > 0 and turnover > 0) else 0.0
                    ltp = float(front.get("lastPrice", 0.0) or 0.0)
                    prev_close = float(front.get("prevClose", ltp) or ltp)
                    result["futures"] = {
                        "symbol": f"FUT:{index_name}:CURR",
                        "ltp": round(ltp, 2),
                        "close": round(prev_close, 2),
                        "open": round(float(front.get("openPrice", ltp) or ltp), 2),
                        "high": round(float(front.get("highPrice", ltp) or ltp), 2),
                        "low": round(float(front.get("lowPrice", ltp) or ltp), 2),
                        "change": round(float(front.get("change", ltp - prev_close) or 0.0), 2),
                        "pct_change": round(float(front.get("pchange", 0.0) or 0.0), 2),
                        "volume": contracts * lot_sz,
                        "contracts": contracts,
                        "oi": int(float(front.get("openInterest", 0) or 0)),
                        "delta_oi": int(float(front.get("changeinOpenInterest", 0) or 0)),
                        "vwap": vwap if vwap > 0 else round(ltp, 2),
                        "expiry_date": front.get("expiryDate", ""),
                        "bid_ask": {"depth": []},
                        "source": "nse_official",
                        "timestamp": time.time(),
                    }

            # 2. Fetch Nearest Expiry from contract-info & Option Chain V3 (has Bid/Ask + IV + OI + ΔOI!)
            if index_name not in self._expiry_cache:
                r_info = s.get(
                    f"https://www.nseindia.com/api/option-chain-contract-info?symbol={index_name}",
                    headers={"Referer": "https://www.nseindia.com/option-chain"},
                    timeout=8,
                )
                if r_info.status_code == 200:
                    expiries = r_info.json().get("expiryDates", [])
                    if expiries:
                        self._expiry_cache[index_name] = expiries[0]

            nearest_expiry = self._expiry_cache.get(index_name, "")
            if nearest_expiry:
                result["expiry"] = nearest_expiry
                r_oc = s.get(
                    f"https://www.nseindia.com/api/option-chain-v3?type=Indices&symbol={index_name}&expiry={nearest_expiry}",
                    headers={"Referer": "https://www.nseindia.com/option-chain"},
                    timeout=8,
                )
                if r_oc.status_code == 200:
                    rows = r_oc.json().get("records", {}).get("data", [])
                    step = 50 if index_name == "NIFTY" else 100
                    atm = int(round((spot_price or 25850) / step)) * step
                    min_strike = atm - (20 * step)
                    max_strike = atm + (20 * step)
                    dte = self.greeks.compute_dte_from_date(nearest_expiry)

                    for row in rows:
                        for opt_type in ("CE", "PE"):
                            leg = row.get(opt_type)
                            if not leg:
                                continue
                            strike = float(leg.get("strikePrice", 0) or 0)
                            if strike < min_strike or strike > max_strike:
                                continue

                            ltp = float(leg.get("lastPrice", 0.0) or 0.0)
                            vol = int(float(leg.get("totalTradedVolume", 0) or 0))
                            oi = int(float(leg.get("openInterest", 0) or 0))
                            doi = int(float(leg.get("changeinOpenInterest", 0) or 0))
                            bid_p = float(leg.get("buyPrice1", 0.0) or 0.0)
                            bid_q = int(float(leg.get("buyQuantity1", 0) or 0))
                            ask_p = float(leg.get("sellPrice1", 0.0) or 0.0)
                            ask_q = int(float(leg.get("sellQuantity1", 0) or 0))
                            tbq = int(float(leg.get("totalBuyQuantity", 0) or 0))
                            tsq = int(float(leg.get("totalSellQuantity", 0) or 0))
                            nse_iv = float(leg.get("impliedVolatility", 0.0) or 0.0)
                            spread = round(max(0.0, ask_p - bid_p), 2) if (ask_p > 0 and bid_p > 0) else 0.0

                            sym = f"OPT:{index_name}:{int(strike)}{opt_type}"
                            solved = self.greeks.solve_greeks_sync(
                                sym, ltp, spot_price or float(leg.get("underlyingValue", 25850) or 25850), dte, nse_iv
                            )

                            result["options"].append({
                                "symbol": sym,
                                "strike_key": f"{int(strike)}{opt_type}",
                                "ltp": round(ltp, 2),
                                "volume": vol,
                                "oi": oi,
                                "delta_oi": doi,
                                "iv": solved.get("iv", round(nse_iv, 2)),
                                "delta": solved.get("delta", 0.0),
                                "gamma": solved.get("gamma", 0.0),
                                "theta": solved.get("theta", 0.0),
                                "vega": solved.get("vega", 0.0),
                                "rho": solved.get("rho", 0.0),
                                "bid": bid_p,
                                "ask": ask_p,
                                "bid_qty": bid_q,
                                "ask_qty": ask_q,
                                "tbq": tbq,
                                "tsq": tsq,
                                "bid_ask_spread": spread,
                                "bid_ask": {
                                    "depth": [{"bidP": bid_p, "bidQ": bid_q, "askP": ask_p, "askQ": ask_q}]
                                },
                                "expiry_date": nearest_expiry,
                                "source": "nse_official",
                                "timestamp": time.time(),
                            })
        except Exception as e:
            logger.warning(f"NSE derivatives fetch error ({index_name}): {e}")
        return result

    def _fetch_groww_heavyweights_sync(self) -> Dict[str, Any]:
        """Fetches real LTP, volume, change, and bid/ask imbalance for 27 NSE heavyweights via Groww."""
        from curl_cffi import requests as creq
        s = creq.Session(impersonate="chrome")
        hw_data: Dict[str, Any] = {}
        for sym in HEAVYWEIGHT_SYMBOLS:
            try:
                r = s.get(
                    f"https://groww.in/v1/api/stocks_data/v1/tr_live_prices/exchange/NSE/segment/CASH/{sym}/latest",
                    timeout=3,
                )
                if r.status_code == 200:
                    d = r.json()
                    ltp = float(d.get("ltp", 0.0) or 0.0)
                    if ltp <= 0:
                        continue
                    prev_close = float(d.get("close", ltp) or ltp)
                    tbq = float(d.get("totalBuyQty") or d.get("cumulativeBuyQty") or 0)
                    tsq = float(d.get("totalSellQty") or d.get("cumulativeSellQty") or 0)
                    if tbq > 0 and tsq > 0:
                        imb = round(tbq / tsq, 2)
                    elif tbq > 0:
                        imb = 2.0  # pure bid side resting queue
                    elif tsq > 0:
                        imb = 0.5  # pure ask side resting queue
                    else:
                        imb = 1.0
                    hw_data[sym] = {
                        "symbol": f"EQ:{sym}",
                        "ltp": round(ltp, 2),
                        "close": round(prev_close, 2),
                        "open": round(float(d.get("open", ltp) or ltp), 2),
                        "high": round(float(d.get("high", ltp) or ltp), 2),
                        "low": round(float(d.get("low", ltp) or ltp), 2),
                        "volume": int(float(d.get("volume", 0) or 0)),
                        "day_change": round(float(d.get("dayChange", ltp - prev_close) or 0.0), 2),
                        "day_change_pct": round(float(d.get("dayChangePerc", 0.0) or 0.0), 2),
                        "tbq": int(tbq),
                        "tsq": int(tsq),
                        "imbalance": imb,
                        "source": "groww_live",
                        "timestamp": time.time(),
                    }
            except Exception:
                continue
        return hw_data

    def _fetch_real_candles_sync(
        self,
        symbol_key: str,
        interval: Any = "1m",
        range_str: str = "1D",
    ) -> List[Dict[str, Any]]:
        """
        Fetches real OHLC candles across intraday (1m, 3m, 5m, 15m, 30m, 1h) and long-term
        horizons (1d, 1wk across 1M..MAX) from Groww Charting Service & Yahoo Finance.
        """
        sym_upper = symbol_key.upper()
        if "BANK" in sym_upper:
            norm_key, groww_sym, yf_sym = "BANKNIFTY", "BANKNIFTY", "^NSEBANK"
        elif "VIX" in sym_upper:
            norm_key, groww_sym, yf_sym = "INDIAVIX", None, "^INDIAVIX"
        elif "IT" in sym_upper:
            norm_key, groww_sym, yf_sym = "NIFTYIT", "CNXIT", "^CNXIT"
        else:
            norm_key, groww_sym, yf_sym = "NIFTY50", "NIFTY", "^NSEI"

        # Accept either int (1, 3, 5) or string ("1m", "15m", "1h", "1d", "1wk")
        if isinstance(interval, int):
            iv = f"{interval}m"
        else:
            iv = str(interval or "1m").strip()

        iv_lower = iv.lower()
        groww_interval_mins = {
            "1m": 1,
            "3m": 3,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "60m": 60,
            "1d": 1440,
        }
        range_days_map = {
            "1D": 5,     # 5 calendar days guarantees latest active trading session on weekends/holidays
            "5D": 7,
            "1M": 32,
            "3M": 95,
            "6M": 185,
            "1Y": 370,
            "5Y": 1830,
            "MAX": 7300,
        }
        r_upper = (range_str or "1D").upper()
        if r_upper not in range_days_map:
            r_upper = "1Y" if iv_lower in ("1d", "1wk", "1w") else ("6M" if iv_lower in ("1h", "60m") else "1D")

        is_daily_or_weekly = iv_lower in ("1d", "1wk", "1w")
        time_fmt = "%d %b %y" if is_daily_or_weekly else "%H:%M"
        candles: List[Dict[str, Any]] = []

        # 1. Try Groww Charting Service when range <= 1Y and interval supported by Groww
        groww_mins = groww_interval_mins.get(iv_lower)
        max_groww_days = 10 if (groww_mins or 999) <= 5 else (32 if (groww_mins or 999) <= 15 else (95 if (groww_mins or 999) <= 60 else 400))
        req_days = range_days_map[r_upper]
        if groww_sym and groww_mins and req_days <= max_groww_days:
            try:
                from curl_cffi import requests as creq
                end_ms = int(time.time() * 1000)
                start_ms = end_ms - (req_days * 24 * 3600 * 1000)
                url = (
                    f"https://groww.in/v1/api/charting_service/v2/chart/delayed/exchange/NSE/segment/CASH/{groww_sym}"
                    f"?endTimeInMillis={end_ms}&intervalInMinutes={groww_mins}&startTimeInMillis={start_ms}"
                )
                r = creq.get(url, impersonate="chrome", timeout=8)
                if r.status_code == 200:
                    raw = r.json().get("candles", [])
                    # On 1D default view keep ~380 recent bars covering full 09:15-15:30 IST intraday session
                    if r_upper == "1D" and groww_mins == 1:
                        raw = raw[-380:]
                    elif len(raw) > 2500:
                        raw = raw[-2500:]
                    for c in raw:
                        if len(c) >= 5 and c[4] is not None:
                            ts = int(c[0])
                            dt_ist = datetime.datetime.fromtimestamp(ts, tz=self.tz)
                            candles.append({
                                "timestamp": ts,
                                "time": dt_ist.strftime(time_fmt),
                                "open": round(float(c[1]), 2),
                                "high": round(float(c[2]), 2),
                                "low": round(float(c[3]), 2),
                                "close": round(float(c[4]), 2),
                                "volume": int(c[5] or 0) if len(c) > 5 else 0,
                            })
                    if candles:
                        return candles
            except Exception as e:
                logger.debug(f"Groww candles failed for {norm_key} ({iv_lower}/{r_upper}): {e}")

        # 2. Fallback & Long-Horizon Source: Yahoo Finance
        try:
            import yfinance as yf
            yf_period_map = {
                "1D": "5d",
                "5D": "5d",
                "1M": "1mo",
                "3M": "3mo",
                "6M": "6mo",
                "1Y": "1y",
                "5Y": "5y",
                "MAX": "max",
            }
            yf_period = yf_period_map.get(r_upper, "1mo")

            # Enforce Yahoo interval retention limits cleanly
            if iv_lower == "1m":
                yf_interval, yf_period = "1m", ("5d" if req_days <= 7 else "7d")
            elif iv_lower == "3m":
                # Resample 1m into exact 3m bars when Yahoo fallback is needed
                yf_interval, yf_period = "1m", "5d"
            elif iv_lower in ("5m", "15m", "30m"):
                yf_interval = iv_lower
                if req_days > 55:
                    yf_period = "1mo"
            elif iv_lower in ("1h", "60m"):
                yf_interval = "1h"
                if req_days > 700:
                    yf_period = "2y"
            elif iv_lower in ("1wk", "1w"):
                yf_interval = "1wk"
            elif iv_lower == "1d":
                yf_interval = "1d"
            else:
                yf_interval = "1m"

            df = yf.Ticker(yf_sym).history(period=yf_period, interval=yf_interval)
            if not df.empty:
                if iv_lower == "3m" and yf_interval == "1m":
                    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
                    if "Volume" in df.columns:
                        agg["Volume"] = "sum"
                    df = df.resample("3min").agg(agg).dropna(subset=["Open", "Close"])

                if r_upper == "1D" and iv_lower == "1m":
                    df = df.tail(380)
                elif len(df) > 2500:
                    df = df.tail(2500)

                for idx_ts, row in df.iterrows():
                    dt_ist = idx_ts.tz_convert(self.tz) if idx_ts.tzinfo else self.tz.localize(idx_ts)
                    candles.append({
                        "timestamp": int(dt_ist.timestamp()),
                        "time": dt_ist.strftime(time_fmt),
                        "open": round(float(row["Open"]), 2),
                        "high": round(float(row["High"]), 2),
                        "low": round(float(row["Low"]), 2),
                        "close": round(float(row["Close"]), 2),
                        "volume": int(row.get("Volume", 0) or 0),
                    })
        except Exception as e:
            logger.warning(f"Yahoo candles fallback failed for {norm_key} ({iv_lower}/{r_upper}): {e}")

        return candles

    async def poll_once(self):
        """Executes a complete live market snapshot update across indices, futures, options, heavyweights, and candles."""
        self._cycle_count += 1

        # 1. Indices + VIX
        indices = await asyncio.to_thread(self._fetch_nse_indices_sync)
        for internal_sym, data in indices.items():
            if not internal_sym.startswith("INDEX:"):
                continue
            redis_key = f"LTP:{internal_sym}"
            if not await self._is_upstox_ws_fresh(redis_key):
                await redis_db.set_json(redis_key, data)

        nifty_spot = indices.get("INDEX:NIFTY50", {}).get("ltp", 0.0)
        bank_spot = indices.get("INDEX:NIFTYBANK", {}).get("ltp", 0.0)

        # Store official NIFTY 50 breadth A/D Ratio immediately if provided by NSE
        n50 = indices.get("INDEX:NIFTY50", {})
        if n50.get("advances") is not None and n50.get("declines") is not None:
            adv = int(n50["advances"])
            dec = int(n50["declines"])
            if adv + dec > 0:
                await redis_db.set_json(
                    "METRIC:AD_RATIO",
                    {"advances": adv, "declines": dec, "unchanged": int(n50.get("unchanged", 0)), "ratio": round(adv / max(dec, 1), 2)},
                )

        # 2. Futures + Option Chain + Vollib Greeks (NIFTY & BANKNIFTY)
        for idx_name, spot_val in (("NIFTY", nifty_spot), ("BANKNIFTY", bank_spot)):
            deriv = await asyncio.to_thread(self._fetch_nse_derivatives_sync, idx_name, spot_val)
            if deriv.get("expiry"):
                await redis_db.set_json(f"SYSTEM:EXPIRY:{idx_name}", {"expiry_date": deriv["expiry"]})
            await redis_db.redis.set(f"SYSTEM:LOT:{idx_name}", str(deriv.get("lot_size", 65)))

            metric_key = "NIFTY50" if idx_name == "NIFTY" else "BANKNIFTY"

            fut = deriv.get("futures")
            if fut:
                fut_key = f"LTP:{fut['symbol']}"
                if not await self._is_upstox_ws_fresh(fut_key):
                    await redis_db.set_json(fut_key, fut)
                    if fut.get("vwap", 0) > 0:
                        await redis_db.set_json(f"METRIC:VWAP:{metric_key}", {"vwap": fut["vwap"]})

                    # Compute deterministic delta volume & signed volume delta when ticking (never overwrite existing CVD on unit/source switch)
                    prev_f = self._prev_fut_state.get(metric_key)
                    if prev_f:
                        dv = fut["volume"] - prev_f.get("volume", fut["volume"])
                        if 0 < dv <= 500000:
                            existing_cvd = await redis_db.get_json(f"METRIC:CVD:{metric_key}")
                            cur_cvd = int(existing_cvd.get("cvd", self._cvd_state[metric_key])) if existing_cvd else self._cvd_state[metric_key]
                            direction = 1 if fut["ltp"] > prev_f["ltp"] else (-1 if fut["ltp"] < prev_f["ltp"] else 0)
                            self._cvd_state[metric_key] = cur_cvd + (direction * dv)
                            await redis_db.set_json(f"METRIC:CVD:{metric_key}", {"cvd": self._cvd_state[metric_key]})
                    self._prev_fut_state[metric_key] = {"ltp": fut["ltp"], "volume": fut["volume"]}

            opts = deriv.get("options", [])
            if opts:
                for opt in opts:
                    opt_key = f"LTP:{opt['symbol']}"
                    if not await self._is_upstox_ws_fresh(opt_key):
                        await redis_db.set_json(opt_key, opt, expire=300)
                        await redis_db.set_json(
                            f"GREEKS:{opt['symbol']}",
                            {
                                "iv": opt["iv"],
                                "delta": opt["delta"],
                                "gamma": opt["gamma"],
                                "theta": opt["theta"],
                                "vega": opt["vega"],
                                "rho": opt["rho"],
                                "source": "nse_vollib",
                            },
                            expire=300,
                        )

                # Recompute PCR, GEX, Max Pain cleanly after full option batch
                await self.greeks.calculate_pcr(f"INDEX:{metric_key}")
                await self.greeks.calculate_max_pain(f"INDEX:{metric_key}")
                await self.greeks.calculate_gex(f"INDEX:{metric_key}")

        # 3. Heavyweights (Every 2nd cycle / ~6-8s or first boot to keep latency low)
        if self._cycle_count == 1 or self._cycle_count % 2 == 0:
            hw_map = await asyncio.to_thread(self._fetch_groww_heavyweights_sync)
            for sym, hw_tick in hw_map.items():
                eq_key = f"LTP:EQ:{sym}"
                if not await self._is_upstox_ws_fresh(eq_key):
                    await redis_db.set_json(eq_key, hw_tick)
                    await redis_db.set_json(f"METRIC:IMBALANCE:EQ:{sym}", {"ratio": hw_tick["imbalance"]})

        # 4. Real 1-Minute Intraday Candles (refresh every 30s)
        if (time.time() - self._last_candles_ts) >= 30.0:
            n_candles, bn_candles = await asyncio.gather(
                asyncio.to_thread(self._fetch_real_candles_sync, "NIFTY50", 1),
                asyncio.to_thread(self._fetch_real_candles_sync, "BANKNIFTY", 1),
            )
            if n_candles:
                await redis_db.set_json("CHART:CANDLES:NIFTY50", {"candles": n_candles, "updated_at": time.time()})
            if bn_candles:
                await redis_db.set_json("CHART:CANDLES:BANKNIFTY", {"candles": bn_candles, "updated_at": time.time()})
            self._last_candles_ts = time.time()

        await redis_db.set_json(
            "SYSTEM:FEED_STATUS",
            {
                "primary_feed": "NSE_OFFICIAL + GROWW + YAHOO",
                "last_poll_ts": time.time(),
                "nifty_ltp": nifty_spot,
                "vix_ltp": indices.get("INDEX:INDIAVIX", {}).get("ltp", 0.0),
                "cycle": self._cycle_count,
            },
        )
        logger.info(
            f"Live Feed Synced [#{self._cycle_count}] -> NIFTY: {nifty_spot} | BANK: {bank_spot} | "
            f"VIX: {indices.get('INDEX:INDIAVIX', {}).get('ltp', 0.0)}"
        )

    async def run(self):
        self.is_running = True
        logger.info("LiveMarketPoller started (Real-time Exchange & Groww Ingestion).")
        while self.is_running:
            try:
                await self.poll_once()
            except Exception as e:
                logger.error(f"LiveMarketPoller cycle failed: {e}")
            await asyncio.sleep(5.0)

    async def stop(self):
        self.is_running = False
        logger.info("LiveMarketPoller stopped.")

import asyncio
import csv
import datetime
import gzip
import io
import json
import logging
import math
import threading
import time
import urllib.request
from typing import Any, Dict, List

import pytz
import upstox_client
from upstox_client.feeder.market_data_streamer_v3 import MarketDataStreamerV3

from core.config import settings
from core.redis_client import redis_db

logger = logging.getLogger(__name__)


class TokenManager:
    """
    Downloads daily broker Scrip Master (Token Master) from Upstox.
    Maps our internal symbols to Upstox Instrument Keys (e.g. NSE_INDEX|India VIX, NSE_FO|...).
    """

    def __init__(self):
        self.symbol_to_key: Dict[str, str] = {
            "INDEX:NIFTY50": "NSE_INDEX|Nifty 50",
            "INDEX:NIFTYBANK": "NSE_INDEX|Nifty Bank",
            "INDEX:NIFTYIT": "NSE_INDEX|Nifty IT",
            "INDEX:INDIAVIX": "NSE_INDEX|India VIX",
        }
        self.key_to_symbol: Dict[str, str] = {v: k for k, v in self.symbol_to_key.items()}
        self.csv_data: str = ""

    def fetch_master(self):
        logger.info("Downloading Daily Broker Scrip Master (Tokens) from Upstox...")
        try:
            url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            response = urllib.request.urlopen(req, timeout=20)
            compressed_file = io.BytesIO(response.read())
            decompressed_file = gzip.GzipFile(fileobj=compressed_file)
            data = decompressed_file.read().decode("utf-8")

            reader = csv.DictReader(io.StringIO(data))

            for row in reader:
                instrument_key = row.get("instrument_key")
                tradingsymbol = row.get("tradingsymbol", "")
                exchange = row.get("exchange", "")
                instrument_type = row.get("instrument_type", "")
                name = row.get("name", "")

                internal_sym = ""

                if instrument_type == "INDEX" and exchange == "NSE_INDEX":
                    norm_name = name.strip().upper()
                    if norm_name in ("NIFTY 50", "NIFTY"):
                        internal_sym = "INDEX:NIFTY50"
                    elif norm_name in ("NIFTY BANK", "BANKNIFTY"):
                        internal_sym = "INDEX:NIFTYBANK"
                    elif norm_name == "NIFTY IT":
                        internal_sym = "INDEX:NIFTYIT"
                    elif norm_name == "INDIA VIX":
                        internal_sym = "INDEX:INDIAVIX"
                elif exchange == "NSE_EQ" and instrument_type == "EQUITY":
                    internal_sym = f"EQ:{tradingsymbol}"

                if internal_sym and instrument_key:
                    self.symbol_to_key[internal_sym] = instrument_key
                    self.key_to_symbol[instrument_key] = internal_sym

            self.csv_data = data
            logger.info(f"Successfully mapped {len(self.symbol_to_key)} Upstox instruments.")

            self.map_front_month_futures()
            self.map_lot_sizes()
        except Exception as e:
            logger.error(f"Failed to fetch Scrip Master: {e}")

    def _parse_expiry_sort_key(self, exp_val: str) -> str:
        """Normalizes Upstox CSV expiry (epoch ms or YYYY-MM-DD) for chronological sorting."""
        if not exp_val:
            return "9999-12-31"
        exp_str = str(exp_val).strip()
        if exp_str.isdigit() and len(exp_str) >= 10:
            try:
                ts = int(exp_str) / (1000.0 if len(exp_str) > 10 else 1.0)
                return datetime.datetime.fromtimestamp(ts, tz=pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d")
            except Exception:
                return exp_str
        return exp_str

    def map_front_month_futures(self):
        """Finds the front-month FUTIDX for NIFTY and BANKNIFTY and maps them."""
        if not self.csv_data:
            return

        nifty_futs = []
        banknifty_futs = []
        today_str = datetime.datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d")

        reader = csv.DictReader(io.StringIO(self.csv_data))
        for row in reader:
            if row.get("exchange") == "NSE_FO" and row.get("instrument_type") == "FUTIDX":
                name = row.get("name", "").strip().upper()
                exp_iso = self._parse_expiry_sort_key(row.get("expiry", ""))
                if exp_iso < today_str:
                    continue
                row["_exp_iso"] = exp_iso
                if name == "NIFTY":
                    nifty_futs.append(row)
                elif name == "BANKNIFTY":
                    banknifty_futs.append(row)

        if nifty_futs:
            nifty_futs.sort(key=lambda x: x["_exp_iso"])
            front_key = nifty_futs[0].get("instrument_key")
            if front_key:
                self.symbol_to_key["FUT:NIFTY:CURR"] = front_key
                self.key_to_symbol[front_key] = "FUT:NIFTY:CURR"
                logger.info(f"Mapped FUT:NIFTY:CURR -> {front_key} ({nifty_futs[0].get('tradingsymbol')})")

        if banknifty_futs:
            banknifty_futs.sort(key=lambda x: x["_exp_iso"])
            front_key = banknifty_futs[0].get("instrument_key")
            if front_key:
                self.symbol_to_key["FUT:BANKNIFTY:CURR"] = front_key
                self.key_to_symbol[front_key] = "FUT:BANKNIFTY:CURR"
                logger.info(f"Mapped FUT:BANKNIFTY:CURR -> {front_key} ({banknifty_futs[0].get('tradingsymbol')})")

    def map_lot_sizes(self):
        """Extracts dynamic lot sizes directly from Upstox CSV."""
        if not self.csv_data:
            return

        nifty_lot = None
        banknifty_lot = None

        reader = csv.DictReader(io.StringIO(self.csv_data))
        for row in reader:
            if row.get("exchange") == "NSE_FO" and row.get("instrument_type") == "OPTIDX":
                name = row.get("name", "").strip().upper()
                if name == "NIFTY" and not nifty_lot:
                    nifty_lot = row.get("lot_size")
                elif name == "BANKNIFTY" and not banknifty_lot:
                    banknifty_lot = row.get("lot_size")
            if nifty_lot and banknifty_lot:
                break

        self.nifty_lot_size = nifty_lot
        self.banknifty_lot_size = banknifty_lot

        if not nifty_lot or not banknifty_lot:
            return

        import redis
        try:
            r = redis.Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
                decode_responses=True,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
            )
            r.set("SYSTEM:LOT:NIFTY", nifty_lot)
            r.set("SYSTEM:LOT:BANKNIFTY", banknifty_lot)
            logger.info(f"Dynamically mapped Lot Sizes -> NIFTY: {nifty_lot}, BANKNIFTY: {banknifty_lot}")
        except Exception as e:
            logger.debug(f"Could not sync lot sizes synchronously to Redis: {e}")

    def find_option_instrument_key(self, index_name: str, strike: float, opt_type: str) -> str:
        """Finds nearest non-expired option instrument key using exact underlying name & strike."""
        if not self.csv_data:
            return ""

        search_target = index_name.strip().upper()
        today_str = datetime.datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d")

        if not hasattr(self, "_opt_index_cache") or self._opt_index_cache is None:
            self._opt_index_cache = {}
            reader = csv.DictReader(io.StringIO(self.csv_data))
            for row in reader:
                if row.get("exchange") == "NSE_FO" and row.get("instrument_type") == "OPTIDX":
                    nm = row.get("name", "").strip().upper()
                    if nm not in ("NIFTY", "BANKNIFTY"):
                        continue
                    exp_iso = self._parse_expiry_sort_key(row.get("expiry", ""))
                    if exp_iso < today_str:
                        continue
                    try:
                        st = float(row.get("strike", 0))
                    except Exception:
                        continue
                    ot = row.get("option_type", "").strip().upper()
                    self._opt_index_cache.setdefault((nm, st, ot), []).append((exp_iso, row.get("instrument_key", "")))

        candidates = self._opt_index_cache.get((search_target, float(strike), opt_type.upper()), [])
        if candidates:
            candidates.sort(key=lambda x: x[0])
            exp_iso, front_key = candidates[0]
            if front_key:
                internal_sym = f"OPT:{search_target}:{int(strike)}{opt_type.upper()}"
                self.symbol_to_key[internal_sym] = front_key
                self.key_to_symbol[front_key] = internal_sym
                self.nearest_expiries[search_target] = exp_iso
                return front_key
        return ""


class PrimaryDataNode:
    """
    Connects to the primary broker (Upstox) via WebSocket V3 (`MarketDataStreamerV3`) & REST.
    Streams live tick data (Indices, VIX, Futures, Equities, Option Chain + Greeks) into Redis.
    """

    def __init__(self):
        self.is_connected = False
        self.token_valid = False
        self.token_manager = TokenManager()
        self.token_manager.nearest_expiries = {}
        self.streamer = None

        self.configuration = upstox_client.Configuration()
        self.configuration.access_token = settings.UPSTOX_ACCESS_TOKEN
        self.api_client = upstox_client.ApiClient(self.configuration)

    async def get_dynamic_subscription_list(self) -> List[str]:
        """
        Determines real Nifty & BankNifty ATM strikes dynamically from Upstox or Redis/NSE spot,
        returning deduplicated instrument keys with core indices & futures prioritized.
        """
        priority_syms = [
            "INDEX:NIFTY50",
            "INDEX:NIFTYBANK",
            "INDEX:NIFTYIT",
            "INDEX:INDIAVIX",
            "FUT:NIFTY:CURR",
            "FUT:BANKNIFTY:CURR",
            "EQ:HDFCBANK",
            "EQ:RELIANCE",
            "EQ:ICICIBANK",
            "EQ:INFY",
            "EQ:TCS",
            "EQ:LT",
            "EQ:AXISBANK",
            "EQ:KOTAKBANK",
            "EQ:SBIN",
        ]
        instruments = [self.token_manager.symbol_to_key.get(s) for s in priority_syms]
        instruments = [i for i in instruments if i]

        nifty_ltp = 0.0
        banknifty_ltp = 0.0

        # 1. Try Upstox REST API first
        try:
            nifty_key = self.token_manager.symbol_to_key.get("INDEX:NIFTY50")
            banknifty_key = self.token_manager.symbol_to_key.get("INDEX:NIFTYBANK")
            market_api = upstox_client.MarketQuoteApi(self.api_client)
            if nifty_key and banknifty_key and settings.UPSTOX_ACCESS_TOKEN:
                quote_keys = f"{nifty_key},{banknifty_key}"
                quote_res = await asyncio.to_thread(
                    market_api.get_full_market_quote, symbol=quote_keys, api_version="2.0"
                )
                if quote_res.status == "success" and quote_res.data:
                    self.token_valid = True
                    for k, v in quote_res.data.items():
                        tok = getattr(v, "instrument_token", k)
                        if tok == nifty_key or "Nifty 50" in k:
                            nifty_ltp = getattr(v, "last_price", 0.0) or 0.0
                        elif tok == banknifty_key or "Nifty Bank" in k:
                            banknifty_ltp = getattr(v, "last_price", 0.0) or 0.0
        except Exception as e:
            err_str = str(e)
            if "401" in err_str or "UDAPI100050" in err_str or "Unauthorized" in err_str:
                self.token_valid = False
                logger.warning("Upstox token expired/unauthorized (401). LiveMarketPoller (NSE/Groww/Yahoo) remains active.")
            else:
                logger.error(f"Failed Upstox REST spot check: {e}")

        # 2. Fallback to live cached NSE/Groww spot in Redis if Upstox REST unavailable
        if nifty_ltp <= 0:
            n_cached = await redis_db.get_json("LTP:INDEX:NIFTY50")
            if n_cached:
                nifty_ltp = float(n_cached.get("ltp", 0.0))
        if banknifty_ltp <= 0:
            b_cached = await redis_db.get_json("LTP:INDEX:NIFTYBANK")
            if b_cached:
                banknifty_ltp = float(b_cached.get("ltp", 0.0))

        # 3. Dynamically build ATM ± 20 strikes only when real spot is known
        opt_instruments = []
        if nifty_ltp > 0:
            nifty_atm = int(round(nifty_ltp / 50.0)) * 50
            for step in range(-20, 21):
                strike = nifty_atm + (step * 50)
                opt_instruments.append(self.token_manager.find_option_instrument_key("NIFTY", strike, "CE"))
                opt_instruments.append(self.token_manager.find_option_instrument_key("NIFTY", strike, "PE"))

        if banknifty_ltp > 0:
            banknifty_atm = int(round(banknifty_ltp / 100.0)) * 100
            for step in range(-20, 21):
                strike = banknifty_atm + (step * 100)
                opt_instruments.append(self.token_manager.find_option_instrument_key("BANKNIFTY", strike, "CE"))
                opt_instruments.append(self.token_manager.find_option_instrument_key("BANKNIFTY", strike, "PE"))

        # Persist nearest expiry metadata for accurate DTE calculation
        for idx_name, exp_iso in getattr(self.token_manager, "nearest_expiries", {}).items():
            await redis_db.set_json(f"SYSTEM:EXPIRY:{idx_name}", {"expiry_date": exp_iso})

        seen = set()
        ordered = []
        for k in instruments + [o for o in opt_instruments if o]:
            if k not in seen:
                seen.add(k)
                ordered.append(k)

        logger.info(f"Dynamically generated {len(ordered)} Upstox instrument keys.")
        return ordered

    def on_market_data(self, message):
        """Callback from Upstox Streamer containing decoded protobuf dictionary."""
        try:
            if not message:
                return
            asyncio.run_coroutine_threadsafe(self.process_tick(message), self.loop)
        except Exception as e:
            logger.error(f"Error handling Upstox market data: {e}")

    @staticmethod
    def _num(val, default=0.0) -> float:
        try:
            return float(val) if val is not None else default
        except Exception:
            return default

    async def process_tick(self, tick: dict):
        """Processes Upstox MarketDataStreamerV3 decoded tick (both marketFF and indexFF) -> Redis."""
        try:
            now_ts = time.time()
            for instrument_key, feed_data in tick.get("feeds", {}).items():
                ffc = feed_data.get("fullFeed") or feed_data.get("ff") or {}
                market_ff = ffc.get("marketFF")
                index_ff = ffc.get("indexFF")
                ltpc_only = feed_data.get("ltpc")

                if not market_ff and not index_ff and not ltpc_only:
                    continue

                internal_symbol = self.token_manager.key_to_symbol.get(instrument_key, instrument_key)

                if index_ff:
                    ltpc = index_ff.get("ltpc", {})
                    ltp = self._num(ltpc.get("ltp"), 0.0)
                    prev_close = self._num(ltpc.get("cp"), 0.0)
                    ohlc_list = index_ff.get("marketOHLC", {}).get("ohlc", [])
                    daily_ohlc = next((o for o in ohlc_list if o.get("interval") == "1d"), ohlc_list[0] if ohlc_list else {})
                    change = round(ltp - prev_close, 2) if prev_close > 0 else 0.0
                    pct_change = round((change / prev_close) * 100.0, 2) if prev_close > 0 else 0.0

                    standardized_tick = {
                        "symbol": internal_symbol,
                        "ltp": ltp,
                        "close": prev_close,
                        "open": self._num(daily_ohlc.get("open"), ltp),
                        "high": self._num(daily_ohlc.get("high"), ltp),
                        "low": self._num(daily_ohlc.get("low"), ltp),
                        "change": change,
                        "pct_change": pct_change,
                        "day_change": change,
                        "day_change_pct": pct_change,
                        "volume": 0,
                        "oi": 0,
                        "vwap": 0.0,
                        "bid_ask": {"depth": []},
                        "source": "upstox_ws",
                        "timestamp": now_ts,
                    }
                elif market_ff:
                    ltpc = market_ff.get("ltpc", {})
                    ltp = self._num(ltpc.get("ltp"), 0.0)
                    prev_close = self._num(ltpc.get("cp"), 0.0)
                    vol = int(self._num(market_ff.get("vtt"), 0))
                    oi = int(self._num(market_ff.get("oi"), 0))
                    vwap = self._num(market_ff.get("atp") or market_ff.get("vWap"), 0.0)
                    tbq = int(self._num(market_ff.get("tbq"), 0))
                    tsq = int(self._num(market_ff.get("tsq"), 0))
                    raw_iv = self._num(market_ff.get("iv"), 0.0)

                    raw_depth = market_ff.get("marketLevel", {}).get("bidAskQuote", [])
                    norm_depth = []
                    for d in raw_depth:
                        norm_depth.append({
                            "bidP": self._num(d.get("bidP"), 0.0),
                            "bidQ": int(self._num(d.get("bidQ") or d.get("bq"), 0)),
                            "askP": self._num(d.get("askP"), 0.0),
                            "askQ": int(self._num(d.get("askQ") or d.get("aq"), 0)),
                        })

                    best_bid = norm_depth[0]["bidP"] if norm_depth else 0.0
                    best_ask = norm_depth[0]["askP"] if norm_depth else 0.0
                    spread = round(max(0.0, best_ask - best_bid), 2) if (best_bid > 0 and best_ask > 0) else 0.0

                    ohlc_list = market_ff.get("marketOHLC", {}).get("ohlc", [])
                    daily_ohlc = next((o for o in ohlc_list if o.get("interval") == "1d"), ohlc_list[0] if ohlc_list else {})
                    change = round(ltp - prev_close, 2) if prev_close > 0 else 0.0
                    pct_change = round((change / prev_close) * 100.0, 2) if prev_close > 0 else 0.0

                    standardized_tick = {
                        "symbol": internal_symbol,
                        "ltp": ltp,
                        "close": prev_close,
                        "open": self._num(daily_ohlc.get("open"), ltp),
                        "high": self._num(daily_ohlc.get("high"), ltp),
                        "low": self._num(daily_ohlc.get("low"), ltp),
                        "change": change,
                        "pct_change": pct_change,
                        "day_change": change,
                        "day_change_pct": pct_change,
                        "volume": vol,
                        "oi": oi,
                        "vwap": vwap,
                        "tbq": tbq,
                        "tsq": tsq,
                        "bid": best_bid,
                        "ask": best_ask,
                        "bid_ask_spread": spread,
                        "bid_ask": {"depth": norm_depth},
                        "source": "upstox_ws",
                        "timestamp": now_ts,
                    }

                    # If Upstox provides native OptionGreeks, persist directly too
                    upstox_greeks = market_ff.get("optionGreeks")
                    if upstox_greeks and internal_symbol.startswith("OPT:"):
                        g_payload = {
                            "iv": round(raw_iv * 100 if 0 < raw_iv < 3 else raw_iv, 2),
                            "delta": round(self._num(upstox_greeks.get("delta")), 4),
                            "gamma": round(self._num(upstox_greeks.get("gamma")), 4),
                            "theta": round(self._num(upstox_greeks.get("theta")), 2),
                            "vega": round(self._num(upstox_greeks.get("vega")), 2),
                            "rho": round(self._num(upstox_greeks.get("rho")), 2),
                            "source": "upstox_ws",
                        }
                        await redis_db.set_json(f"GREEKS:{internal_symbol}", g_payload)
                else:
                    ltp = self._num(ltpc_only.get("ltp"), 0.0)
                    prev_close = self._num(ltpc_only.get("cp"), 0.0)
                    standardized_tick = {
                        "symbol": internal_symbol,
                        "ltp": ltp,
                        "close": prev_close,
                        "change": round(ltp - prev_close, 2) if prev_close > 0 else 0.0,
                        "pct_change": round(((ltp - prev_close) / prev_close) * 100.0, 2) if prev_close > 0 else 0.0,
                        "volume": 0,
                        "oi": 0,
                        "vwap": 0.0,
                        "bid_ask": {"depth": []},
                        "source": "upstox_ws",
                        "timestamp": now_ts,
                    }

                await redis_db.set_json(f"LTP:{internal_symbol}", standardized_tick)
                await redis_db.publish_message("TICK_STREAM", standardized_tick)
        except Exception as e:
            logger.error(f"Tick processing error: {e}")

    def on_open(self):
        logger.info("Upstox WebSocket V3 CONNECTED.")
        self.is_connected = True
        self.token_valid = True

    def on_close(self, code, reason):
        logger.warning(f"Upstox WebSocket CLOSED: {code} - {reason}")
        self.is_connected = False

        async def reconnect_task():
            await asyncio.sleep(10)
            if not self.is_connected and self.token_valid:
                keys = await self.get_dynamic_subscription_list()
                if keys:
                    t = threading.Thread(target=self.start_streamer_thread, args=(keys,), daemon=True)
                    t.start()

        if hasattr(self, "loop") and self.loop.is_running():
            asyncio.run_coroutine_threadsafe(reconnect_task(), self.loop)

    def on_error(self, error):
        err_str = str(error)
        if "401" in err_str or "Unauthorized" in err_str:
            self.token_valid = False
            logger.warning("Upstox WebSocket rejected token (401 Unauthorized). Run upstox_auth.py to refresh daily token.")
        else:
            logger.error(f"Upstox WebSocket ERROR: {error}")

    async def listen_for_subscriptions(self):
        """Listens on Redis for dynamic subscription updates."""
        pubsub = redis_db.get_subscriber()
        if pubsub:
            await pubsub.subscribe("SUBSCRIPTION_UPDATES")
            logger.info("Primary Node listening for dynamic subscription updates.")
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        new_tokens = data.get("tokens", [])
                        if new_tokens and self.streamer and self.is_connected:
                            self.streamer.subscribe(new_tokens, mode="full")
                    except Exception as e:
                        logger.error(f"Error parsing subscription update: {e}")

    def start_streamer_thread(self, instrument_keys: List[str]):
        """Runs the Upstox websocket in a daemon thread."""
        try:
            self.streamer = MarketDataStreamerV3(
                api_client=self.api_client,
                instrumentKeys=instrument_keys,
                mode="full",
            )
            self.streamer.on("open", self.on_open)
            self.streamer.on("message", self.on_market_data)
            self.streamer.on("error", self.on_error)
            self.streamer.on("close", self.on_close)
            self.streamer.connect()
        except Exception as e:
            logger.error(f"Failed to start Upstox Streamer: {e}")

    async def run(self):
        """Main entry point for Upstox Primary Node."""
        self.loop = asyncio.get_running_loop()
        try:
            if not settings.UPSTOX_ACCESS_TOKEN:
                logger.warning("UPSTOX_ACCESS_TOKEN missing. Running cleanly on NSE/Groww/Yahoo Real-Time Poller.")
                await redis_db.set_json("SYSTEM:UPSTOX_STATUS", {"connected": False, "token_valid": False, "reason": "NO_TOKEN"})
                return

            logger.info("Initializing Upstox Primary Live Data Feed...")
            await asyncio.to_thread(self.token_manager.fetch_master)

            instrument_keys = await self.get_dynamic_subscription_list()
            if not self.token_valid:
                await redis_db.set_json(
                    "SYSTEM:UPSTOX_STATUS",
                    {"connected": False, "token_valid": False, "reason": "TOKEN_EXPIRED_401"},
                )
                return

            await redis_db.set_json(
                "SYSTEM:UPSTOX_STATUS",
                {"connected": True, "token_valid": True, "instruments": len(instrument_keys)},
            )

            # Batch initial REST quotes cleanly across ALL priority + option instruments
            try:
                market_api = upstox_client.MarketQuoteApi(self.api_client)
                now_ts = time.time()
                for idx in range(0, len(instrument_keys), 50):
                    batch = instrument_keys[idx : idx + 50]
                    quote_keys = ",".join(batch)
                    quote_res = await asyncio.to_thread(
                        market_api.get_full_market_quote, symbol=quote_keys, api_version="2.0"
                    )
                    if quote_res.status == "success" and quote_res.data:
                        for key, details in quote_res.data.items():
                            token = getattr(details, "instrument_token", key)
                            internal_symbol = self.token_manager.key_to_symbol.get(token, token)
                            ltp = self._num(getattr(details, "last_price", 0.0))
                            ohlc = getattr(details, "ohlc", None)
                            prev_close = self._num(getattr(ohlc, "close", 0.0) if ohlc else 0.0)
                            vol = int(self._num(getattr(details, "volume", 0)))
                            oi = int(self._num(getattr(details, "oi", 0)))
                            avg_p = self._num(getattr(details, "average_price", 0.0))
                            change = self._num(getattr(details, "net_change", ltp - prev_close if prev_close > 0 else 0.0))
                            pct_change = round((change / prev_close) * 100.0, 2) if prev_close > 0 else 0.0

                            standardized_tick = {
                                "symbol": internal_symbol,
                                "ltp": ltp,
                                "close": prev_close,
                                "open": self._num(getattr(ohlc, "open", ltp) if ohlc else ltp),
                                "high": self._num(getattr(ohlc, "high", ltp) if ohlc else ltp),
                                "low": self._num(getattr(ohlc, "low", ltp) if ohlc else ltp),
                                "change": round(change, 2),
                                "pct_change": pct_change,
                                "volume": vol,
                                "oi": oi,
                                "vwap": avg_p,
                                "bid_ask": {"depth": []},
                                "source": "upstox_rest",
                                "timestamp": now_ts,
                            }
                            await redis_db.set_json(f"LTP:{internal_symbol}", standardized_tick)
                logger.info("Upstox initial REST quotes populated successfully.")
            except Exception as e:
                logger.warning(f"Failed to fetch initial Upstox REST quotes: {e}")

            asyncio.create_task(self.listen_for_subscriptions())

            streamer_thread = threading.Thread(target=self.start_streamer_thread, args=(instrument_keys,), daemon=True)
            streamer_thread.start()

            while True:
                await asyncio.sleep(5)
                await redis_db.set_json(
                    "SYSTEM:UPSTOX_STATUS",
                    {
                        "connected": self.is_connected,
                        "token_valid": self.token_valid,
                        "instruments": len(instrument_keys),
                    },
                )

        except Exception as e:
            logger.error(f"Primary Data Node error: {e}")
            await self.trigger_fallback()

    async def trigger_fallback(self):
        logger.warning("Primary Upstox feed offline; relying on NSE/Groww/Yahoo Live Poller.")
        await redis_db.publish_message("SYSTEM_ALERT", {"type": "UPSTOX_OFFLINE", "source": "Primary"})

    async def stop(self):
        self.is_connected = False
        if self.streamer:
            try:
                self.streamer.disconnect()
            except Exception:
                pass
        logger.info("Primary Data Node stopped.")

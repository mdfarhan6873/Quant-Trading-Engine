import asyncio
import json
import logging
import math
import urllib.request
import csv
import io
import gzip
import threading
from typing import Dict, Any, List

import upstox_client
from upstox_client.feeder.market_data_streamer_v3 import MarketDataStreamerV3

from core.redis_client import redis_db
from core.config import settings

logger = logging.getLogger(__name__)

class TokenManager:
    """
    Downloads daily broker Scrip Master (Token Master) from Upstox.
    Maps our internal symbols to Upstox Instrument Keys (e.g. NSE_FO|...)
    """
    def __init__(self):
        self.symbol_to_key = {}
        self.key_to_symbol = {}
        
    def fetch_master(self):
        logger.info("Downloading Daily Broker Scrip Master (Tokens) from Upstox...")
        try:
            url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
            response = urllib.request.urlopen(url)
            compressed_file = io.BytesIO(response.read())
            decompressed_file = gzip.GzipFile(fileobj=compressed_file)
            data = decompressed_file.read().decode('utf-8')
            
            reader = csv.DictReader(io.StringIO(data))
            
            for row in reader:
                instrument_key = row.get("instrument_key")
                tradingsymbol = row.get("tradingsymbol", "")
                exchange = row.get("exchange", "")
                instrument_type = row.get("instrument_type", "")
                name = row.get("name", "")
                
                internal_sym = ""
                
                if instrument_type == "INDEX":
                    if name == "Nifty 50":
                        internal_sym = "INDEX:NIFTY50"
                    elif name == "Nifty Bank":
                        internal_sym = "INDEX:NIFTYBANK"
                    elif name == "Nifty IT":
                        internal_sym = "INDEX:NIFTYIT"
                    elif name == "India VIX":
                        internal_sym = "INDEX:INDIAVIX"
                elif exchange == "NSE_EQ" and instrument_type == "EQ":
                    internal_sym = f"EQ:{tradingsymbol}"
                elif exchange == "NSE_FO":
                    if instrument_type == "OPTIDX":
                        # Upstox tradingsymbol for options looks like: NIFTY24APR22500CE
                        # We will map standard options to our format later, but for exact mapping, 
                        # we can rely on strike, expiry, option_type if needed.
                        # For simplicity, we just use tradingsymbol here and the system will request the exact tradingsymbol.
                        # But wait, our get_dynamic_subscription_list uses standard OPT:NIFTY:22500CE.
                        # We need a robust matcher for Options. Let's just store the row data and we will search dynamically.
                        pass
                        
                if internal_sym and instrument_key:
                    self.symbol_to_key[internal_sym] = instrument_key
                    self.key_to_symbol[instrument_key] = internal_sym
                    
            logger.info(f"Successfully mapped {len(self.symbol_to_key)} exact instruments. Option chain will be built dynamically.")
            self.csv_data = data # Store for dynamic searches
            
            # Map futures and lot sizes
            self.map_front_month_futures()
            self.map_lot_sizes()
        except Exception as e:
            logger.error(f"Failed to fetch Scrip Master: {e}")

    def map_front_month_futures(self):
        """Finds the front-month FUTIDX for NIFTY and BANKNIFTY and maps them."""
        if not hasattr(self, 'csv_data'):
            return
            
        nifty_futs = []
        banknifty_futs = []
        
        reader = csv.DictReader(io.StringIO(self.csv_data))
        for row in reader:
            if row.get("instrument_type") == "FUTIDX":
                name = row.get("name")
                if name == "NIFTY":
                    nifty_futs.append(row)
                elif name == "BANKNIFTY":
                    banknifty_futs.append(row)
                    
        # Sort by expiry and get the nearest
        if nifty_futs:
            nifty_futs.sort(key=lambda x: x.get("expiry", ""))
            front_key = nifty_futs[0].get("instrument_key")
            if front_key:
                internal_sym = "FUT:NIFTY:CURR"
                self.symbol_to_key[internal_sym] = front_key
                self.key_to_symbol[front_key] = internal_sym
                logger.info(f"Mapped {internal_sym} -> {front_key}")
                
        if banknifty_futs:
            banknifty_futs.sort(key=lambda x: x.get("expiry", ""))
            front_key = banknifty_futs[0].get("instrument_key")
            if front_key:
                internal_sym = "FUT:BANKNIFTY:CURR"
                self.symbol_to_key[internal_sym] = front_key
                self.key_to_symbol[front_key] = internal_sym
                logger.info(f"Mapped {internal_sym} -> {front_key}")

    def map_lot_sizes(self):
        """Extracts dynamic lot sizes directly from the exchange to handle SEBI updates seamlessly."""
        if not hasattr(self, 'csv_data'):
            return
            
        nifty_lot = None
        banknifty_lot = None
        
        reader = csv.DictReader(io.StringIO(self.csv_data))
        for row in reader:
            if row.get("instrument_type") == "OPTIDX":
                if row.get("name") == "NIFTY" and not nifty_lot:
                    nifty_lot = row.get("lot_size")
                if row.get("name") == "BANKNIFTY" and not banknifty_lot:
                    banknifty_lot = row.get("lot_size")
            if nifty_lot and banknifty_lot:
                break
                
        if not nifty_lot or not banknifty_lot:
            return

        import redis
        try:
            r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)
            r.set("SYSTEM:LOT:NIFTY", nifty_lot)
            r.set("SYSTEM:LOT:BANKNIFTY", banknifty_lot)
            logger.info(f"Dynamically mapped Lot Sizes -> NIFTY: {nifty_lot}, BANKNIFTY: {banknifty_lot}")
        except Exception as e:
            logger.error(f"Failed to save lot sizes to redis: {e}")

    def find_option_instrument_key(self, index_name: str, strike: float, opt_type: str) -> str:
        """Helper to find the nearest expiring option instrument key based on strike."""
        # This is a simplified search. A real implementation would parse dates and find the nearest expiry.
        # For now, we will return a dummy key if not found, or use a naive string search on the CSV data.
        # e.g., NIFTY...22500...CE
        # To make it super robust, we can parse the CSV and filter.
        # Implementing a fast filter:
        if not hasattr(self, 'csv_data'):
            return ""
        
        search_target = f"{index_name.upper()}"
        strike_str = str(float(strike))
        
        reader = csv.DictReader(io.StringIO(self.csv_data))
        valid_options = []
        for row in reader:
            if row.get("instrument_type") == "OPTIDX" and row.get("option_type") == opt_type and float(row.get("strike", 0)) == strike:
                if row.get("tradingsymbol", "").startswith(search_target):
                    valid_options.append(row)
        
        if valid_options:
            # Sort by expiry to get the closest one
            valid_options.sort(key=lambda x: x.get("expiry", ""))
            return valid_options[0].get("instrument_key", "")
        return ""


class PrimaryDataNode:
    """
    Connects to the primary broker (Upstox) via WebSocket using upstox-python-sdk.
    Streams live tick data and option chain updates into Redis.
    """
    def __init__(self):
        self.is_connected = False
        self.token_manager = TokenManager()
        self.streamer = None
        
        self.configuration = upstox_client.Configuration()
        self.configuration.access_token = settings.UPSTOX_ACCESS_TOKEN
        self.api_client = upstox_client.ApiClient(self.configuration)

    async def get_dynamic_subscription_list(self) -> List[str]:
        """
        Dynamically fetches the actual Nifty and BankNifty ATM strikes and calculates
        the ± 20 strikes dynamically. Returns Upstox Instrument Keys directly.
        """
        instruments = [
            self.token_manager.symbol_to_key.get("INDEX:NIFTY50"),
            self.token_manager.symbol_to_key.get("INDEX:NIFTYBANK"),
            self.token_manager.symbol_to_key.get("INDEX:INDIAVIX"),
            # Futures
            self.token_manager.symbol_to_key.get("FUT:NIFTY:CURR"),
            self.token_manager.symbol_to_key.get("FUT:BANKNIFTY:CURR"),
            # Add heavyweights
            self.token_manager.symbol_to_key.get("EQ:HDFCBANK"),
            self.token_manager.symbol_to_key.get("EQ:RELIANCE"),
            self.token_manager.symbol_to_key.get("EQ:ICICIBANK"),
            self.token_manager.symbol_to_key.get("EQ:INFY")
        ]
        
        # Remove Nones
        instruments = [i for i in instruments if i]

        try:
            import nsepython
            # 1. Fetch REAL Nifty 50 spot price
            nifty_quote = nsepython.nse_quote("NIFTY 50")
            nifty_ltp = nifty_quote.get("priceInfo", {}).get("lastPrice", 0.0) if nifty_quote else 22500
            
            if nifty_ltp > 0:
                nifty_atm = int(math.floor(nifty_ltp / 50.0)) * 50
                for step in range(-20, 21):
                    strike = nifty_atm + (step * 50)
                    instruments.append(self.token_manager.find_option_instrument_key("NIFTY", strike, "CE"))
                    instruments.append(self.token_manager.find_option_instrument_key("NIFTY", strike, "PE"))

            # 2. Fetch REAL BankNifty spot price
            banknifty_quote = nsepython.nse_quote("NIFTY BANK")
            banknifty_ltp = banknifty_quote.get("priceInfo", {}).get("lastPrice", 0.0) if banknifty_quote else 47500

            if banknifty_ltp > 0:
                banknifty_atm = int(math.floor(banknifty_ltp / 100.0)) * 100
                for step in range(-20, 21):
                    strike = banknifty_atm + (step * 100)
                    instruments.append(self.token_manager.find_option_instrument_key("BANKNIFTY", strike, "CE"))
                    instruments.append(self.token_manager.find_option_instrument_key("BANKNIFTY", strike, "PE"))

            instruments = [i for i in instruments if i]
            logger.info(f"Dynamically generated {len(instruments)} live Upstox tokens.")
        except Exception as e:
            logger.error(f"Failed to fetch dynamic Option Chain strikes: {e}")
            
        return list(set(instruments))

    def on_market_data(self, message):
        """Callback from Upstox Streamer containing decoded protobuf data."""
        # Upstox streamer sends updates. Let's push to redis in async-safe manner.
        try:
            # message is already a decoded dictionary from upstox SDK
            if not message:
                return
            
            # Use asyncio to dispatch the redis update
            asyncio.run_coroutine_threadsafe(self.process_tick(message), self.loop)
        except Exception as e:
            logger.error(f"Error handling market data: {e}")

    async def process_tick(self, tick: dict):
        """Processes the Upstox decoded tick and writes to Redis."""
        try:
            for instrument_key, feed_data in tick.get("feeds", {}).items():
                
                ffc = feed_data.get("ff") # Full Feed
                if not ffc:
                    continue
                    
                market_ff = ffc.get("marketFF")
                if not market_ff:
                    continue

                ltp = market_ff.get("ltpc", {}).get("ltp", 0.0)
                vol = market_ff.get("vtt", 0)
                oi = market_ff.get("oi", 0)
                
                # Market Depth
                bids = market_ff.get("marketLevel", {}).get("bidAskQuote", [])
                
                internal_symbol = self.token_manager.key_to_symbol.get(instrument_key, instrument_key)

                standardized_tick = {
                    "symbol": internal_symbol,
                    "ltp": ltp,
                    "close": market_ff.get("ltpc", {}).get("cp", 0.0),
                    "volume": vol,
                    "oi": oi, 
                    "bid_ask": {"depth": bids}
                }

                await redis_db.set_json(f"LTP:{internal_symbol}", standardized_tick)
                await redis_db.publish_message("TICK_STREAM", standardized_tick)
        except Exception as e:
            logger.error(f"Tick processing error: {e}")

    def on_open(self):
        logger.info("Upstox WebSocket CONNECTED.")
        self.is_connected = True

    def on_close(self, code, reason):
        logger.warning(f"Upstox WebSocket CLOSED: {code} - {reason}")
        self.is_connected = False
        # Instead of dying permanently, trigger a soft restart internally before failing over
        logger.info("Attempting auto-reconnect in 5 seconds...")
        async def reconnect_task():
            await asyncio.sleep(5)
            if not self.is_connected:
                # Re-fetch keys and re-initialize streamer thread
                keys = await self.get_dynamic_subscription_list()
                if keys:
                    import threading
                    t = threading.Thread(target=self.start_streamer_thread, args=(keys,))
                    t.daemon = True
                    t.start()
                else:
                    await self.trigger_fallback()
        asyncio.run_coroutine_threadsafe(reconnect_task(), self.loop)

    def on_error(self, error):
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
                        if new_tokens and self.streamer:
                            logger.info(f"Received dynamic subscription update: {len(new_tokens)} tokens")
                            self.streamer.subscribe(new_tokens, mode="full")
                    except Exception as e:
                        logger.error(f"Error parsing subscription update: {e}")

    def start_streamer_thread(self, instrument_keys: List[str]):
        """Runs the Upstox websocket in a separate thread so it doesn't block asyncio."""
        try:
            self.streamer = MarketDataStreamerV3(
                api_client=self.api_client, 
                instrumentKeys=instrument_keys, 
                mode="full"
            )
            
            self.streamer.on("open", self.on_open)
            self.streamer.on("message", self.on_market_data)
            self.streamer.on("error", self.on_error)
            self.streamer.on("close", self.on_close)
            
            # This is a blocking call, hence running in a thread
            self.streamer.connect()
        except Exception as e:
            logger.error(f"Failed to start Upstox Streamer: {e}")

    async def run(self):
        """Main entry point for Primary Node."""
        self.loop = asyncio.get_running_loop()
        try:
            logger.info("Initializing Upstox Primary Live Data Feed...")
            self.token_manager.fetch_master()
            
            instrument_keys = await self.get_dynamic_subscription_list()
            
            if not instrument_keys:
                logger.error("No valid instruments to subscribe to. Exiting.")
                return

            if not settings.UPSTOX_ACCESS_TOKEN:
                logger.critical("UPSTOX_ACCESS_TOKEN is missing! Please run upstox_auth.py to get it.")
                return
                
            # Pre-fetch initial market state (vital when market is closed and WebSocket is silent)
            try:
                logger.info("Fetching initial REST quotes to populate offline data...")
                market_api = upstox_client.MarketQuoteApi(self.api_client)
                quote_keys = ",".join(instrument_keys[:50]) # API limit might be 50 or 500, keeping safe
                quote_res = market_api.get_full_market_quote(symbol=quote_keys, api_version="2.0")
                if quote_res.status == "success":
                    for key, details in quote_res.data.items():
                        instrument_token = details.instrument_token
                        internal_symbol = self.token_manager.key_to_symbol.get(instrument_token, instrument_token)
                        
                        standardized_tick = {
                            "symbol": internal_symbol,
                            "ltp": details.last_price or 0.0,
                            "close": details.ohlc.close if hasattr(details, 'ohlc') and details.ohlc else 0.0,
                            "volume": getattr(details, 'volume', 0) or 0,
                            "oi": getattr(details, 'oi', 0) or 0,
                            "bid_ask": {"depth": []}
                        }
                        await redis_db.set_json(f"LTP:{internal_symbol}", standardized_tick)
                    logger.info("Initial REST quotes populated successfully.")
            except Exception as e:
                logger.warning(f"Failed to fetch initial REST quotes: {e}")

            asyncio.create_task(self.listen_for_subscriptions())
            
            # Start streamer in background thread
            streamer_thread = threading.Thread(target=self.start_streamer_thread, args=(instrument_keys,))
            streamer_thread.daemon = True
            streamer_thread.start()
            
            # Keep asyncio loop alive
            while True:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"Primary Data Node crashed: {e}")
            await self.trigger_fallback()

    async def trigger_fallback(self):
        logger.critical("PRIMARY DATA NODE FAILURE! Triggering Fallback Node...")
        await redis_db.publish_message("SYSTEM_ALERT", {"type": "DATA_NODE_CRASH", "source": "Primary"})

    async def stop(self):
        self.is_connected = False
        if self.streamer:
            self.streamer.disconnect()
        logger.info("Primary Data Node stopped.")

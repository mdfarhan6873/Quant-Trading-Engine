import asyncio
import logging
import json
from typing import Dict, Any
from core.redis_client import redis_db
from core.config import settings

logger = logging.getLogger(__name__)

class OrderflowEngine:
    """
    Computes real-time Orderflow metrics from raw tick data.
    These are the ultra-fast computations that run directly on the tick stream.
    
    Metrics Calculated:
    1. Cumulative Volume Delta (CVD)
    2. Put-Call Ratio (PCR)
    3. Futures Premium/Discount
    4. VWAP (Volume Weighted Average Price)
    5. Advance/Decline (A/D) Ratio
    6. Order Book Imbalance
    """
    def __init__(self):
        self.is_running = False
        # State variables for continuous aggregation
        self.cumulative_volume_delta = {"NIFTY50": 0, "BANKNIFTY": 0}
        self.vwap_state = {"NIFTY50": {"cumulative_pv": 0, "cumulative_vol": 0}, 
                           "BANKNIFTY": {"cumulative_pv": 0, "cumulative_vol": 0}}
        self.adv_dec = {"advances": 0, "declines": 0}
        
    async def process_tick(self, tick: Dict[str, Any]):
        """Processes a single tick instantly and updates metrics in Redis."""
        symbol = tick.get("symbol", "")
        ltp = tick.get("ltp", 0.0)
        vol = tick.get("volume", 0)
        
        # Extract previous tick state to get tick_volume
        prev_tick_str = await redis_db.redis.get(f"PREV_TICK:{symbol}")
        prev_ltp = ltp
        prev_vol = vol
        if prev_tick_str:
            prev_tick = json.loads(prev_tick_str)
            prev_ltp = prev_tick.get("ltp", ltp)
            prev_vol = prev_tick.get("volume", vol)
            
        tick_volume = vol - prev_vol
        if tick_volume < 0: # Reset on new day or bad tick
            tick_volume = vol
            
        # 1. Update VWAP (using exact tick volume)
        if symbol == "INDEX:NIFTY50" or symbol == "FUT:NIFTY:CURR":
            base = "NIFTY50"
            self.vwap_state[base]["cumulative_pv"] += (ltp * tick_volume)
            self.vwap_state[base]["cumulative_vol"] += tick_volume
            if self.vwap_state[base]["cumulative_vol"] > 0:
                vwap = self.vwap_state[base]["cumulative_pv"] / self.vwap_state[base]["cumulative_vol"]
                await redis_db.set_json(f"METRIC:VWAP:{base}", {"vwap": round(vwap, 2)})
                
        elif symbol == "INDEX:NIFTYBANK" or symbol == "FUT:BANKNIFTY:CURR":
            base = "BANKNIFTY"
            self.vwap_state[base]["cumulative_pv"] += (ltp * tick_volume)
            self.vwap_state[base]["cumulative_vol"] += tick_volume
            if self.vwap_state[base]["cumulative_vol"] > 0:
                vwap = self.vwap_state[base]["cumulative_pv"] / self.vwap_state[base]["cumulative_vol"]
                await redis_db.set_json(f"METRIC:VWAP:{base}", {"vwap": round(vwap, 2)})
                
        # 2. Cumulative Volume Delta (CVD)
        # Tick goes up -> Buy Volume (+), Tick goes down -> Sell Volume (-)
        if prev_tick_str and tick_volume > 0:
            direction = 1 if ltp > prev_ltp else (-1 if ltp < prev_ltp else 0)
            if symbol == "FUT:NIFTY:CURR":
                self.cumulative_volume_delta["NIFTY50"] += (direction * tick_volume)
                await redis_db.set_json("METRIC:CVD:NIFTY50", {"cvd": self.cumulative_volume_delta["NIFTY50"]})
            elif symbol == "FUT:BANKNIFTY:CURR":
                self.cumulative_volume_delta["BANKNIFTY"] += (direction * tick_volume)
                await redis_db.set_json("METRIC:CVD:BANKNIFTY", {"cvd": self.cumulative_volume_delta["BANKNIFTY"]})

        # Save this tick as prev for next calculation
        await redis_db.set_json(f"PREV_TICK:{symbol}", tick)
        
        # 3. Order Book Imbalance (Top 5 Bid/Ask)
        depth = tick.get("bid_ask", {})
        bids = depth.get("bids", [])
        asks = depth.get("asks", [])
        
        total_bid_qty = sum(b.get("qty", 0) for b in bids)
        total_ask_qty = sum(a.get("qty", 0) for a in asks)
        
        if total_ask_qty > 0:
            imbalance = round(total_bid_qty / total_ask_qty, 2)
        else:
            imbalance = 1.0 # Neutral if no asks
            
        await redis_db.set_json(f"METRIC:IMBALANCE:{symbol}", {"ratio": imbalance})

    async def calculate_pcr(self):
        """Periodically scans all Option OIs to calculate Put-Call Ratio for both indices."""
        indices = [("NIFTY", "NIFTY50"), ("BANKNIFTY", "BANKNIFTY")]
        
        for index_prefix, metric_name in indices:
            try:
                cursor = b'0'
                call_oi = 0
                put_oi = 0
                
                while cursor:
                    # Scan for options of this specific index
                    cursor, keys = await redis_db.redis.scan(cursor, match=f"LTP:OPT:{index_prefix}:*", count=100)
                    for key in keys:
                        data_str = await redis_db.redis.get(key)
                        if data_str:
                            data = json.loads(data_str)
                            symbol = data.get("symbol", "")
                            oi = data.get("oi", 0)
                            if symbol.endswith("CE"):
                                call_oi += oi
                            elif symbol.endswith("PE"):
                                put_oi += oi
                                
                if call_oi > 0:
                    pcr = round(put_oi / call_oi, 2)
                    await redis_db.set_json(f"METRIC:PCR:{metric_name}", {"pcr": pcr})
            except Exception as e:
                logger.error(f"Error calculating PCR for {metric_name}: {e}")

    async def run(self):
        """Listens to the tick stream and continuously calculates orderflow."""
        self.is_running = True
        logger.info("Orderflow Engine (Fast Loop) Started.")
        
        pubsub = redis_db.get_subscriber()
        if not pubsub:
            logger.error("Failed to connect to Redis Pub/Sub")
            return
            
        await pubsub.subscribe("TICK_STREAM")
        
        # Start a background task for periodic metric calculations (like PCR)
        asyncio.create_task(self.periodic_aggregations())
        
        async for message in pubsub.listen():
            if not self.is_running:
                break
            if message["type"] == "message":
                try:
                    tick_data = json.loads(message["data"])
                    await self.process_tick(tick_data)
                except Exception as e:
                    logger.error(f"Orderflow tick processing error: {e}")
                    
    async def calculate_adv_dec(self):
        """Calculates Advance/Decline Ratio by scanning all Equity ticks."""
        try:
            cursor = b'0'
            adv = 0
            dec = 0
            
            while cursor:
                cursor, keys = await redis_db.redis.scan(cursor, match="LTP:EQ:*", count=100)
                for key in keys:
                    data_str = await redis_db.redis.get(key)
                    if data_str:
                        data = json.loads(data_str)
                        ltp = data.get("ltp", 0.0)
                        prev_close = data.get("close", ltp) # close is prev_close in market data
                        
                        if ltp > prev_close:
                            adv += 1
                        elif ltp < prev_close:
                            dec += 1
                            
            if adv + dec > 0:
                ad_ratio = round(adv / max(dec, 1), 2)
                await redis_db.set_json("METRIC:AD_RATIO", {"advances": adv, "declines": dec, "ratio": ad_ratio})
        except Exception as e:
            logger.error(f"Error calculating A/D Ratio: {e}")

    async def periodic_aggregations(self):
        """Runs heavy aggregations like PCR and A/D Ratio every few seconds."""
        while self.is_running:
            await self.calculate_pcr()
            await self.calculate_adv_dec()
            await asyncio.sleep(5) # Calculate every 5 seconds to save CPU

if __name__ == "__main__":
    engine = OrderflowEngine()
    asyncio.run(engine.run())

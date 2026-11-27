import asyncio
import json
import logging
from typing import Any, Dict
from core.redis_client import redis_db

logger = logging.getLogger(__name__)


class OrderflowEngine:
    """
    Computes real-time Orderflow metrics from raw tick data:
    1. Cumulative Volume Delta (CVD)
    2. Put-Call Ratio (PCR)
    3. VWAP (Volume Weighted Average Price)
    4. Advance/Decline (A/D) Ratio
    5. Order Book Imbalance (OBI)
    """

    def __init__(self):
        self.is_running = False
        self.cumulative_volume_delta = {"NIFTY50": 0, "BANKNIFTY": 0}
        self.vwap_state = {
            "NIFTY50": {"cumulative_pv": 0.0, "cumulative_vol": 0},
            "BANKNIFTY": {"cumulative_pv": 0.0, "cumulative_vol": 0},
        }

    async def process_tick(self, tick: Dict[str, Any]):
        """Processes a single tick and updates VWAP, CVD, and Order Book Imbalance."""
        symbol = tick.get("symbol", "")
        ltp = float(tick.get("ltp", 0.0) or 0.0)
        vol = int(float(tick.get("volume", 0) or 0))
        if ltp <= 0:
            return

        prev_tick_str = await redis_db.redis.get(f"PREV_TICK:{symbol}")
        prev_ltp = ltp
        prev_vol = vol
        prev_source = tick.get("source")
        if prev_tick_str:
            prev_tick = json.loads(prev_tick_str)
            prev_ltp = float(prev_tick.get("ltp", ltp) or ltp)
            prev_vol = int(float(prev_tick.get("volume", vol) or vol))
            prev_source = prev_tick.get("source")

        # Never treat source switches (NSE vs Upstox) or session resets (vol < prev_vol) as single-tick surges
        same_source = (prev_source == tick.get("source")) if prev_source else True
        tick_volume = (vol - prev_vol) if (prev_tick_str and same_source and vol >= prev_vol) else 0
        if tick_volume > 500000:
            # Cap single-tick delta spike to protect CVD against feed reconnect jumps
            tick_volume = 0

        # 1. Exchange-computed VWAP if present, otherwise accumulate from tick volume
        tick_vwap = float(tick.get("vwap", 0.0) or 0.0)
        if symbol == "FUT:NIFTY:CURR":
            if tick_vwap > 0:
                await redis_db.set_json("METRIC:VWAP:NIFTY50", {"vwap": round(tick_vwap, 2)})
            elif tick_volume > 0:
                self.vwap_state["NIFTY50"]["cumulative_pv"] += ltp * tick_volume
                self.vwap_state["NIFTY50"]["cumulative_vol"] += tick_volume
                vwap = self.vwap_state["NIFTY50"]["cumulative_pv"] / self.vwap_state["NIFTY50"]["cumulative_vol"]
                await redis_db.set_json("METRIC:VWAP:NIFTY50", {"vwap": round(vwap, 2)})
        elif symbol == "FUT:BANKNIFTY:CURR":
            if tick_vwap > 0:
                await redis_db.set_json("METRIC:VWAP:BANKNIFTY", {"vwap": round(tick_vwap, 2)})
            elif tick_volume > 0:
                self.vwap_state["BANKNIFTY"]["cumulative_pv"] += ltp * tick_volume
                self.vwap_state["BANKNIFTY"]["cumulative_vol"] += tick_volume
                vwap = self.vwap_state["BANKNIFTY"]["cumulative_pv"] / self.vwap_state["BANKNIFTY"]["cumulative_vol"]
                await redis_db.set_json("METRIC:VWAP:BANKNIFTY", {"vwap": round(vwap, 2)})

        # 2. Cumulative Volume Delta (CVD) - preserve prior Redis value cleanly across reconnects
        if prev_tick_str and tick_volume > 0:
            direction = 1 if ltp > prev_ltp else (-1 if ltp < prev_ltp else 0)
            if direction != 0:
                if symbol == "FUT:NIFTY:CURR":
                    if self.cumulative_volume_delta["NIFTY50"] == 0:
                        existing = await redis_db.get_json("METRIC:CVD:NIFTY50")
                        if existing and isinstance(existing.get("cvd"), (int, float)):
                            self.cumulative_volume_delta["NIFTY50"] = int(existing["cvd"])
                    self.cumulative_volume_delta["NIFTY50"] += direction * tick_volume
                    await redis_db.set_json("METRIC:CVD:NIFTY50", {"cvd": int(self.cumulative_volume_delta["NIFTY50"])})
                elif symbol == "FUT:BANKNIFTY:CURR":
                    if self.cumulative_volume_delta["BANKNIFTY"] == 0:
                        existing = await redis_db.get_json("METRIC:CVD:BANKNIFTY")
                        if existing and isinstance(existing.get("cvd"), (int, float)):
                            self.cumulative_volume_delta["BANKNIFTY"] = int(existing["cvd"])
                    self.cumulative_volume_delta["BANKNIFTY"] += direction * tick_volume
                    await redis_db.set_json("METRIC:CVD:BANKNIFTY", {"cvd": int(self.cumulative_volume_delta["BANKNIFTY"])})

        await redis_db.set_json(f"PREV_TICK:{symbol}", tick)

        # 3. Order Book Imbalance (Top 5 Bid/Ask or TBQ/TSQ)
        depth = tick.get("bid_ask", {}).get("depth", [])
        total_bid_qty = sum(float(b.get("bidQ") or b.get("bq") or 0) for b in depth)
        total_ask_qty = sum(float(a.get("askQ") or a.get("aq") or 0) for a in depth)

        if total_bid_qty == 0 and total_ask_qty == 0:
            total_bid_qty = float(tick.get("tbq", 0) or 0)
            total_ask_qty = float(tick.get("tsq", 0) or 0)

        if total_ask_qty > 0:
            imbalance = round(total_bid_qty / total_ask_qty, 2)
            await redis_db.set_json(f"METRIC:IMBALANCE:{symbol}", {"ratio": imbalance})

    async def calculate_pcr(self):
        """Periodically scans all Option OIs to calculate Put-Call Ratio for both indices."""
        indices = [("NIFTY", "NIFTY50"), ("BANKNIFTY", "BANKNIFTY")]

        for index_prefix, metric_name in indices:
            try:
                cursor = 0
                call_oi = 0.0
                put_oi = 0.0

                while True:
                    cursor, keys = await redis_db.redis.scan(cursor, match=f"LTP:OPT:{index_prefix}:*", count=200)
                    for raw_key in keys:
                        key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else raw_key
                        data_str = await redis_db.redis.get(key)
                        if data_str:
                            data = json.loads(data_str)
                            symbol = data.get("symbol", "")
                            oi = float(data.get("oi", 0) or 0)
                            if symbol.endswith("CE"):
                                call_oi += oi
                            elif symbol.endswith("PE"):
                                put_oi += oi
                    if not cursor:
                        break

                if call_oi > 0:
                    pcr = round(put_oi / call_oi, 4)
                    await redis_db.set_json(
                        f"METRIC:PCR:{metric_name}",
                        {"pcr": pcr, "put_oi": put_oi, "call_oi": call_oi},
                    )
            except Exception as e:
                logger.error(f"Error calculating PCR for {metric_name}: {e}")

    async def calculate_adv_dec(self):
        """Calculates Advance/Decline Ratio from NSE index breadth or constituent Equity ticks."""
        try:
            nifty_raw = await redis_db.get_json("LTP:INDEX:NIFTY50")
            if nifty_raw and nifty_raw.get("advances") is not None and nifty_raw.get("declines") is not None:
                adv = int(nifty_raw["advances"])
                dec = int(nifty_raw["declines"])
                if adv + dec > 0:
                    ad_ratio = round(adv / max(dec, 1), 2)
                    await redis_db.set_json(
                        "METRIC:AD_RATIO",
                        {"advances": adv, "declines": dec, "unchanged": int(nifty_raw.get("unchanged", 0)), "ratio": ad_ratio},
                    )
                    return

            cursor = 0
            adv = 0
            dec = 0
            while True:
                cursor, keys = await redis_db.redis.scan(cursor, match="LTP:EQ:*", count=100)
                for raw_key in keys:
                    key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else raw_key
                    data_str = await redis_db.redis.get(key)
                    if data_str:
                        data = json.loads(data_str)
                        ltp = float(data.get("ltp", 0.0) or 0.0)
                        prev_close = float(data.get("close", ltp) or ltp)
                        if ltp > prev_close:
                            adv += 1
                        elif ltp < prev_close:
                            dec += 1
                if not cursor:
                    break

            if adv + dec > 0:
                ad_ratio = round(adv / max(dec, 1), 2)
                await redis_db.set_json("METRIC:AD_RATIO", {"advances": adv, "declines": dec, "ratio": ad_ratio})
        except Exception as e:
            logger.error(f"Error calculating A/D Ratio: {e}")

    async def periodic_aggregations(self):
        """Runs aggregate PCR and A/D Ratio every 5 seconds."""
        while self.is_running:
            await self.calculate_pcr()
            await self.calculate_adv_dec()
            await asyncio.sleep(5)

    async def run(self):
        """Listens to TICK_STREAM and continuously computes orderflow."""
        self.is_running = True
        logger.info("Orderflow Engine (Fast Loop) Started.")

        pubsub = redis_db.get_subscriber()
        if not pubsub:
            logger.error("Failed to attach to Pub/Sub")
            return

        await pubsub.subscribe("TICK_STREAM")
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

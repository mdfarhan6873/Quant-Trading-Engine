import asyncio
import logging
import json
from typing import Dict, Any
from core.redis_client import redis_db
from core.config import settings

logger = logging.getLogger(__name__)

class GreeksEngine:
    """
    Computes Option Greeks, Max Pain, and Gamma Exposure (GEX) from live tick data.
    Uses py_vollib for Black-Scholes calculations.
    """
    def __init__(self):
        self.is_running = False
        self.risk_free_rate = 0.07 # 7% risk-free rate for India
        
    def get_dte(self, symbol: str) -> float:
        """Dynamically calculates Days to Expiry (DTE) based on current real-world date."""
        import datetime
        now = datetime.datetime.now()
        today = now.date()
        
        # Nifty expires on Thursday (3), BankNifty on Wednesday (2)
        target_weekday = 2 if "BANK" in symbol else 3
        
        days_ahead = target_weekday - today.weekday()
        if days_ahead < 0:
            days_ahead += 7
            
        if days_ahead == 0:
            # If today is expiry, calculate exact fraction of day left until 15:30
            expiry_time = datetime.datetime.combine(today, datetime.time(15, 30))
            remaining = (expiry_time - now).total_seconds()
            return max(remaining / 86400.0, 0.001)
        
        return float(days_ahead)

    async def calculate_greeks(self, symbol: str, ltp: float, spot_price: float, expiry_days: float):
        """
        Calculates Delta, Gamma, Theta, Vega, and Implied Volatility (IV)
        using the Black-Scholes model via py_vollib.
        """
        try:
            import vollib.black_scholes.implied_volatility as iv
            import vollib.black_scholes.greeks.analytical as greeks
            
            parts = symbol.split(":")
            if len(parts) < 3: return
            
            strike_type = parts[2]
            strike = float(strike_type[:-2])
            flag = 'c' if strike_type.endswith('CE') else 'p'
            
            t = expiry_days / 365.0
            if t <= 0: t = 0.0001
            
            implied_vol = iv.implied_volatility(ltp, spot_price, strike, t, self.risk_free_rate, flag)
            
            delta = greeks.delta(flag, spot_price, strike, t, self.risk_free_rate, implied_vol)
            gamma = greeks.gamma(flag, spot_price, strike, t, self.risk_free_rate, implied_vol)
            theta = greeks.theta(flag, spot_price, strike, t, self.risk_free_rate, implied_vol)
            
            greek_data = {
                "iv": round(implied_vol * 100, 2),
                "delta": round(delta, 4),
                "gamma": round(gamma, 4),
                "theta": round(theta, 2)
            }
            
            await redis_db.set_json(f"GREEKS:{symbol}", greek_data)
        except Exception as e:
            pass

    async def calculate_max_pain(self, spot_symbol: str):
        """
        Calculates Max Pain for the given index based on live OI.
        """
        try:
            cursor = b'0'
            options = []
            prefix = "NIFTY" if "NIFTY50" in spot_symbol else "BANKNIFTY"
            
            while cursor:
                cursor, keys = await redis_db.redis.scan(cursor, match=f"LTP:OPT:{prefix}:*", count=100)
                for key in keys:
                    data_str = await redis_db.redis.get(key)
                    if data_str:
                        data = json.loads(data_str)
                        symbol = data.get("symbol", "")
                        oi = data.get("oi", 0)
                        
                        strike_type = symbol.split(":")[2]
                        strike = float(strike_type[:-2])
                        flag = 'c' if strike_type.endswith('CE') else 'p'
                        
                        options.append({"strike": strike, "type": flag, "oi": oi})
                        
            if not options: return

            unique_strikes = sorted(list(set([o["strike"] for o in options])))
            min_loss = float('inf')
            max_pain_strike = 0
            
            for candidate_strike in unique_strikes:
                total_loss = 0
                for opt in options:
                    if opt["type"] == 'c' and candidate_strike > opt["strike"]:
                        total_loss += (candidate_strike - opt["strike"]) * opt["oi"]
                    elif opt["type"] == 'p' and candidate_strike < opt["strike"]:
                        total_loss += (opt["strike"] - candidate_strike) * opt["oi"]
                        
                if total_loss < min_loss:
                    min_loss = total_loss
                    max_pain_strike = candidate_strike
                    
            await redis_db.set_json(f"METRIC:MAX_PAIN:{prefix}", {"strike": max_pain_strike, "loss": min_loss})
        except Exception as e:
            logger.error(f"Error calculating Max Pain: {e}")

    async def calculate_gex(self, spot_symbol: str):
        """
        Gamma Exposure (GEX).
        GEX = Sum(Call_Gamma x Call_OI x Spot^2 x 0.01) - Sum(Put_Gamma x Put_OI x Spot^2 x 0.01)
        """
        try:
            spot_str = await redis_db.redis.get(f"LTP:{spot_symbol}")
            if not spot_str: return
            spot_price = json.loads(spot_str).get("ltp", 0.0)
            if spot_price <= 0: return

            cursor = b'0'
            prefix = "NIFTY" if "NIFTY50" in spot_symbol else "BANKNIFTY"
            
            total_gex = 0.0
            
            while cursor:
                cursor, keys = await redis_db.redis.scan(cursor, match=f"GREEKS:OPT:{prefix}:*", count=100)
                for key in keys:
                    greeks_str = await redis_db.redis.get(key)
                    symbol = key.decode("utf-8").replace("GREEKS:", "")
                    ltp_str = await redis_db.redis.get(f"LTP:{symbol}")
                    
                    if greeks_str and ltp_str:
                        greeks = json.loads(greeks_str)
                        ltp_data = json.loads(ltp_str)
                        
                        gamma = greeks.get("gamma", 0.0)
                        oi = ltp_data.get("oi", 0)
                        
                        if oi > 0 and gamma > 0:
                            exposure = gamma * oi * (spot_price ** 2) * 0.01
                            if symbol.endswith("CE"):
                                total_gex += exposure
                            else:
                                total_gex -= exposure
                                
            await redis_db.set_json(f"METRIC:GEX:{prefix}", {"total_gex": total_gex})
            logger.debug(f"Calculated GEX for {prefix}: {total_gex}")
        except Exception as e:
            logger.error(f"Error calculating GEX: {e}")

    async def calculate_pcr(self, spot_symbol: str):
        """
        Calculates Put-Call Ratio (PCR) based on Open Interest.
        PCR = Total Put OI / Total Call OI
        """
        try:
            cursor = b'0'
            total_put_oi = 0
            total_call_oi = 0
            prefix = "NIFTY" if "NIFTY50" in spot_symbol else "BANKNIFTY"
            
            while cursor:
                cursor, keys = await redis_db.redis.scan(cursor, match=f"LTP:OPT:{prefix}:*", count=100)
                for key in keys:
                    data_str = await redis_db.redis.get(key)
                    if data_str:
                        data = json.loads(data_str)
                        symbol = data.get("symbol", "")
                        oi = data.get("oi", 0)
                        
                        if symbol.endswith("CE"):
                            total_call_oi += oi
                        elif symbol.endswith("PE"):
                            total_put_oi += oi
                            
            pcr = round(total_put_oi / total_call_oi, 4) if total_call_oi > 0 else 0
            await redis_db.set_json(f"METRIC:PCR:{prefix}", {"pcr": pcr, "put_oi": total_put_oi, "call_oi": total_call_oi})
            logger.debug(f"Calculated PCR for {prefix}: {pcr}")
        except Exception as e:
            logger.error(f"Error calculating PCR: {e}")

    async def periodic_aggregations(self):
        """Runs heavy calculations periodically (every 10 seconds)."""
        while self.is_running:
            await self.calculate_max_pain("INDEX:NIFTY50")
            await self.calculate_gex("INDEX:NIFTY50")
            await self.calculate_pcr("INDEX:NIFTY50")
            
            await self.calculate_max_pain("INDEX:NIFTYBANK")
            await self.calculate_gex("INDEX:NIFTYBANK")
            await self.calculate_pcr("INDEX:NIFTYBANK")
            await asyncio.sleep(10)

    async def run(self):
        """Listens to the tick stream and computes Greeks in real-time."""
        self.is_running = True
        logger.info("Greeks Engine (Fast Loop) Started.")
        
        pubsub = redis_db.get_subscriber()
        if not pubsub:
            return
            
        await pubsub.subscribe("TICK_STREAM")
        asyncio.create_task(self.periodic_aggregations())
        
        async for message in pubsub.listen():
            if not self.is_running: break
            if message["type"] == "message":
                try:
                    tick_data = json.loads(message["data"])
                    symbol = tick_data.get("symbol", "")
                    
                    if symbol.startswith("OPT:NIFTY") or symbol.startswith("OPT:BANKNIFTY"):
                        index_sym = "INDEX:NIFTY50" if "OPT:NIFTY:" in symbol else "INDEX:NIFTYBANK"
                        spot_str = await redis_db.redis.get(f"LTP:{index_sym}")
                        if spot_str:
                            spot_price = json.loads(spot_str).get("ltp", 0.0)
                            if spot_price > 0:
                                dte = self.get_dte(symbol)
                                await self.calculate_greeks(symbol, tick_data.get("ltp", 0.0), spot_price, dte)
                except Exception as e:
                    pass

if __name__ == "__main__":
    engine = GreeksEngine()
    asyncio.run(engine.run())

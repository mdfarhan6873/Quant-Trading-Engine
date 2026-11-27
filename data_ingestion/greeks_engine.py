import asyncio
import datetime
import json
import logging
import pytz
from typing import Dict, Any
from core.redis_client import redis_db

logger = logging.getLogger(__name__)


class GreeksEngine:
    """
    Computes Option Greeks, Max Pain, Put-Call Ratio, and Gamma Exposure (GEX)
    from live tick data using Black-Scholes via vollib + exact contract expiry DTE.
    """

    def __init__(self):
        self.is_running = False
        self.risk_free_rate = 0.0675  # Prevailing Indian 91-day T-Bill yield (~6.75%)
        self.tz = pytz.timezone("Asia/Kolkata")
        self._expiry_cache: Dict[str, str] = {}

    def compute_dte_from_date(self, expiry_str: str = "") -> float:
        """
        Calculates exact fractional Days to Expiry (DTE) until 15:30 IST on expiry date.
        Supports 'YYYY-MM-DD' and 'DD-Mon-YYYY' (e.g. '01-Dec-2026').
        """
        now = datetime.datetime.now(self.tz)
        expiry_dt = None

        if expiry_str:
            for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y"):
                try:
                    d = datetime.datetime.strptime(expiry_str.strip()[:11], fmt).date()
                    expiry_dt = self.tz.localize(datetime.datetime.combine(d, datetime.time(15, 30)))
                    break
                except Exception:
                    continue

        if expiry_dt is None:
            # Nearest Tuesday fallback for weekly if expiry unavailable
            today = now.date()
            days_ahead = (1 - today.weekday()) % 7
            exp_date = today + datetime.timedelta(days=days_ahead)
            expiry_dt = self.tz.localize(datetime.datetime.combine(exp_date, datetime.time(15, 30)))
            if expiry_dt <= now:
                expiry_dt += datetime.timedelta(days=7)

        remaining_secs = (expiry_dt - now).total_seconds()
        return max(remaining_secs / 86400.0, 0.005)

    def solve_greeks_sync(
        self,
        symbol: str,
        ltp: float,
        spot_price: float,
        expiry_days: float,
        provided_iv: float = 0.0,
    ) -> Dict[str, Any]:
        """Synchronous Black-Scholes solver returning IV, Delta, Gamma, Theta, Vega, Rho."""
        if ltp <= 0 or spot_price <= 0:
            return {}

        try:
            import vollib.black_scholes.implied_volatility as iv_solver
            import vollib.black_scholes.greeks.analytical as greeks_calc

            parts = symbol.split(":")
            if len(parts) < 3:
                return {}

            strike_type = parts[2]
            strike = float(strike_type[:-2])
            flag = "c" if strike_type.endswith("CE") else "p"
            t = max(expiry_days / 365.0, 1.0 / (365.0 * 24.0))

            sigma = (provided_iv / 100.0) if provided_iv and provided_iv > 1.0 else 0.0
            if sigma <= 0.01:
                try:
                    sigma = iv_solver.implied_volatility(ltp, spot_price, strike, t, self.risk_free_rate, flag)
                except Exception:
                    # Fallback estimate when option trades purely at intrinsic or deep ITM/OTM
                    sigma = 0.16

            sigma = max(0.03, min(sigma, 2.5))
            delta = greeks_calc.delta(flag, spot_price, strike, t, self.risk_free_rate, sigma)
            gamma = greeks_calc.gamma(flag, spot_price, strike, t, self.risk_free_rate, sigma)
            theta = greeks_calc.theta(flag, spot_price, strike, t, self.risk_free_rate, sigma)
            vega = greeks_calc.vega(flag, spot_price, strike, t, self.risk_free_rate, sigma)
            rho = greeks_calc.rho(flag, spot_price, strike, t, self.risk_free_rate, sigma)

            return {
                "iv": round(sigma * 100.0, 2),
                "delta": round(delta, 4),
                "gamma": round(gamma, 5),
                "theta": round(theta, 2),
                "vega": round(vega, 2),
                "rho": round(rho, 3),
                "source": "black_scholes_vollib",
            }
        except Exception as e:
            logger.debug(f"Greeks calc skipped for {symbol}: {e}")
            return {}

    async def calculate_greeks(self, symbol: str, ltp: float, spot_price: float, expiry_days: float, provided_iv: float = 0.0):
        res = self.solve_greeks_sync(symbol, ltp, spot_price, expiry_days, provided_iv)
        if res:
            await redis_db.set_json(f"GREEKS:{symbol}", res)

    async def calculate_max_pain(self, spot_symbol: str):
        """Calculates Max Pain strike for the given index based on live OI near current spot."""
        try:
            spot_str = await redis_db.redis.get(f"LTP:{spot_symbol}")
            spot_price = float(json.loads(spot_str).get("ltp", 0.0) or 0.0) if spot_str else 0.0

            cursor = 0
            options = []
            prefix = "NIFTY" if "NIFTY50" in spot_symbol else "BANKNIFTY"

            while True:
                cursor, keys = await redis_db.redis.scan(cursor, match=f"LTP:OPT:{prefix}:*", count=200)
                for raw_key in keys:
                    key = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else raw_key
                    data_str = await redis_db.redis.get(key)
                    if data_str:
                        data = json.loads(data_str)
                        symbol = data.get("symbol", "")
                        oi = float(data.get("oi", 0) or 0)
                        parts = symbol.split(":")
                        if len(parts) >= 3 and oi > 0:
                            strike_type = parts[2]
                            strike = float(strike_type[:-2])
                            if spot_price > 0 and not (spot_price * 0.94 <= strike <= spot_price * 1.06):
                                continue
                            flag = "c" if strike_type.endswith("CE") else "p"
                            options.append({"strike": strike, "type": flag, "oi": oi})
                if not cursor:
                    break

            if not options:
                return

            unique_strikes = sorted({o["strike"] for o in options})
            min_loss = float("inf")
            max_pain_strike = unique_strikes[0]

            for candidate_strike in unique_strikes:
                total_loss = 0.0
                for opt in options:
                    if opt["type"] == "c" and candidate_strike > opt["strike"]:
                        total_loss += (candidate_strike - opt["strike"]) * opt["oi"]
                    elif opt["type"] == "p" and candidate_strike < opt["strike"]:
                        total_loss += (opt["strike"] - candidate_strike) * opt["oi"]
                if total_loss < min_loss:
                    min_loss = total_loss
                    max_pain_strike = candidate_strike

            await redis_db.set_json(f"METRIC:MAX_PAIN:{prefix}", {"strike": max_pain_strike, "loss": min_loss})
        except Exception as e:
            logger.error(f"Error calculating Max Pain: {e}")

    async def calculate_gex(self, spot_symbol: str):
        """
        Calculates Gamma Exposure (GEX):
        GEX = Sum(Call_Gamma * Call_OI * Spot^2 * 0.01) - Sum(Put_Gamma * Put_OI * Spot^2 * 0.01)
        """
        try:
            spot_str = await redis_db.redis.get(f"LTP:{spot_symbol}")
            if not spot_str:
                return
            spot_price = float(json.loads(spot_str).get("ltp", 0.0) or 0.0)
            if spot_price <= 0:
                return

            cursor = 0
            prefix = "NIFTY" if "NIFTY50" in spot_symbol else "BANKNIFTY"
            total_gex = 0.0

            while True:
                cursor, keys = await redis_db.redis.scan(cursor, match=f"GREEKS:OPT:{prefix}:*", count=200)
                for raw_key in keys:
                    key_str = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else raw_key
                    greeks_str = await redis_db.redis.get(key_str)
                    symbol = key_str.replace("GREEKS:", "")
                    ltp_str = await redis_db.redis.get(f"LTP:{symbol}")

                    if greeks_str and ltp_str:
                        greeks = json.loads(greeks_str)
                        ltp_data = json.loads(ltp_str)
                        parts = symbol.split(":")
                        if len(parts) >= 3:
                            strike = float(parts[2][:-2])
                            if not (spot_price * 0.94 <= strike <= spot_price * 1.06):
                                continue
                        gamma = float(greeks.get("gamma", 0.0) or 0.0)
                        oi = float(ltp_data.get("oi", 0) or 0)
                        if oi > 0 and gamma > 0:
                            exposure = gamma * oi * (spot_price ** 2) * 0.01
                            if symbol.endswith("CE"):
                                total_gex += exposure
                            else:
                                total_gex -= exposure
                if not cursor:
                    break

            await redis_db.set_json(f"METRIC:GEX:{prefix}", {"total_gex": round(total_gex, 2)})
        except Exception as e:
            logger.error(f"Error calculating GEX: {e}")

    async def calculate_pcr(self, spot_symbol: str):
        """Calculates Put-Call Ratio (PCR) based on live Open Interest."""
        try:
            spot_str = await redis_db.redis.get(f"LTP:{spot_symbol}")
            spot_price = float(json.loads(spot_str).get("ltp", 0.0) or 0.0) if spot_str else 0.0

            cursor = 0
            total_put_oi = 0.0
            total_call_oi = 0.0
            prefix = "NIFTY" if "NIFTY50" in spot_symbol else "BANKNIFTY"
            metric_key = "NIFTY50" if prefix == "NIFTY" else "BANKNIFTY"

            while True:
                cursor, keys = await redis_db.redis.scan(cursor, match=f"LTP:OPT:{prefix}:*", count=200)
                for raw_key in keys:
                    key_str = raw_key.decode("utf-8") if isinstance(raw_key, bytes) else raw_key
                    data_str = await redis_db.redis.get(key_str)
                    if data_str:
                        data = json.loads(data_str)
                        symbol = data.get("symbol", "")
                        oi = float(data.get("oi", 0) or 0)
                        parts = symbol.split(":")
                        if len(parts) >= 3 and spot_price > 0:
                            strike = float(parts[2][:-2])
                            if not (spot_price * 0.94 <= strike <= spot_price * 1.06):
                                continue
                        if symbol.endswith("CE"):
                            total_call_oi += oi
                        elif symbol.endswith("PE"):
                            total_put_oi += oi
                if not cursor:
                    break

            if total_call_oi > 0:
                pcr = round(total_put_oi / total_call_oi, 4)
                await redis_db.set_json(
                    f"METRIC:PCR:{metric_key}",
                    {"pcr": pcr, "put_oi": total_put_oi, "call_oi": total_call_oi},
                )
        except Exception as e:
            logger.error(f"Error calculating PCR: {e}")

    async def periodic_aggregations(self):
        """Runs aggregate option metrics (Max Pain, GEX, PCR) every 5 seconds."""
        while self.is_running:
            await self.calculate_max_pain("INDEX:NIFTY50")
            await self.calculate_gex("INDEX:NIFTY50")
            await self.calculate_pcr("INDEX:NIFTY50")

            await self.calculate_max_pain("INDEX:NIFTYBANK")
            await self.calculate_gex("INDEX:NIFTYBANK")
            await self.calculate_pcr("INDEX:NIFTYBANK")
            await asyncio.sleep(5)

    async def run(self):
        """Listens to TICK_STREAM and solves Black-Scholes Greeks in real time."""
        self.is_running = True
        logger.info("Greeks Engine (Fast Loop) Started.")

        pubsub = redis_db.get_subscriber()
        if not pubsub:
            return

        await pubsub.subscribe("TICK_STREAM")
        asyncio.create_task(self.periodic_aggregations())

        async for message in pubsub.listen():
            if not self.is_running:
                break
            if message["type"] == "message":
                try:
                    tick_data = json.loads(message["data"])
                    symbol = tick_data.get("symbol", "")
                    if symbol.startswith("OPT:NIFTY:") or symbol.startswith("OPT:BANKNIFTY:"):
                        prefix = "NIFTY" if symbol.startswith("OPT:NIFTY:") else "BANKNIFTY"
                        index_sym = "INDEX:NIFTY50" if prefix == "NIFTY" else "INDEX:NIFTYBANK"
                        spot_str = await redis_db.redis.get(f"LTP:{index_sym}")
                        if spot_str:
                            spot_price = float(json.loads(spot_str).get("ltp", 0.0) or 0.0)
                            if spot_price > 0:
                                exp_str = tick_data.get("expiry_date") or ""
                                if not exp_str:
                                    exp_obj = await redis_db.get_json(f"SYSTEM:EXPIRY:{prefix}")
                                    exp_str = exp_obj.get("expiry_date", "") if exp_obj else ""
                                dte = self.compute_dte_from_date(exp_str)
                                await self.calculate_greeks(
                                    symbol,
                                    float(tick_data.get("ltp", 0.0) or 0.0),
                                    spot_price,
                                    dte,
                                    float(tick_data.get("iv", 0.0) or 0.0),
                                )
                except Exception:
                    pass

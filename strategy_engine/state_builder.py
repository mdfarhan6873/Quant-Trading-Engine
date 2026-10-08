import json
import logging
import datetime
import pytz
from typing import Dict, Any
from core.redis_client import redis_db

logger = logging.getLogger(__name__)

_upstox_holidays_cache = None

def is_market_open() -> bool:
    """Checks if the Indian market is currently open (09:15 to 15:30 IST on weekdays) and not a holiday."""
    global _upstox_holidays_cache
    
    tz = pytz.timezone('Asia/Kolkata')
    now = datetime.datetime.now(tz)
    
    # Check if it's weekend
    if now.weekday() >= 5: # 5=Sat, 6=Sun
        return False
        
    # Check time (09:15 to 15:30)
    market_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)
    
    if not (market_start <= now <= market_end):
        return False
        
    # Check Upstox holiday calendar
    if _upstox_holidays_cache is None:
        try:
            import upstox_client
            api = upstox_client.MarketHolidaysAndTimingsApi()
            resp = api.get_holidays()
            _upstox_holidays_cache = []
            if getattr(resp, 'data', None):
                for h in resp.data:
                    if 'NSE' in getattr(h, 'closed_exchanges', []):
                        _upstox_holidays_cache.append(h._date.date())
        except Exception as e:
            logger.error(f"Failed to fetch Upstox holidays: {e}")
            _upstox_holidays_cache = []  # Cache empty so we don't spam the API on errors
            
    if now.date() in _upstox_holidays_cache:
        return False
        
    return True

class StateBuilder:
    """
    Compresses high-frequency Redis state into a dense, token-efficient JSON payload.
    This acts as the 'Vision' for the LLM Brain in the Slow Loop (every 1-5s).
    """
    def __init__(self):
        # Tracking previous state to calculate momentum/velocity if needed
        self.prev_state = None

    async def build_market_state(self) -> str:
        """
        Gathers all real-time metrics, macro data, and heavyweight orderflow.
        Returns a JSON string strictly optimized for LLM token limits.
        """
        try:
            # 1. Fetch Orderflow Metrics (PCR & CVD)
            nifty_pcr_raw = await redis_db.redis.get("METRIC:PCR:NIFTY50")
            bank_pcr_raw = await redis_db.redis.get("METRIC:PCR:BANKNIFTY")
            nifty_pcr = json.loads(nifty_pcr_raw).get("pcr", 1.0) if nifty_pcr_raw else 1.0
            bank_pcr = json.loads(bank_pcr_raw).get("pcr", 1.0) if bank_pcr_raw else 1.0
            
            nifty_cvd_raw = await redis_db.redis.get("METRIC:CVD:NIFTY50")
            bank_cvd_raw = await redis_db.redis.get("METRIC:CVD:BANKNIFTY")
            nifty_cvd = json.loads(nifty_cvd_raw).get("cvd", 0) if nifty_cvd_raw else 0
            bank_cvd = json.loads(bank_cvd_raw).get("cvd", 0) if bank_cvd_raw else 0

            ad_ratio_raw = await redis_db.redis.get("METRIC:AD_RATIO")
            ad_ratio = json.loads(ad_ratio_raw).get("ratio", 1.0) if ad_ratio_raw else 1.0
            
            # 2. Fetch Greeks & Exposure
            nifty_gex = await redis_db.redis.get("METRIC:GEX:NIFTY")
            nifty_maxpain = await redis_db.redis.get("METRIC:MAX_PAIN:NIFTY")
            banknifty_gex = await redis_db.redis.get("METRIC:GEX:BANKNIFTY")
            banknifty_maxpain = await redis_db.redis.get("METRIC:MAX_PAIN:BANKNIFTY")
            
            nifty_gex_val = json.loads(nifty_gex).get("total_gex", 0.0) if nifty_gex else 0.0
            nifty_maxpain_val = json.loads(nifty_maxpain).get("strike", 0.0) if nifty_maxpain else 0.0
            banknifty_gex_val = json.loads(banknifty_gex).get("total_gex", 0.0) if banknifty_gex else 0.0
            banknifty_maxpain_val = json.loads(banknifty_maxpain).get("strike", 0.0) if banknifty_maxpain else 0.0
            
            # 3. Fetch Spot Indices, Futures, Volumes, VWAP & VIX
            nifty_spot_raw = await redis_db.redis.get("LTP:INDEX:NIFTY50")
            bank_spot_raw = await redis_db.redis.get("LTP:INDEX:NIFTYBANK")
            nifty_it_raw = await redis_db.redis.get("LTP:INDEX:NIFTYIT")
            vix_spot_raw = await redis_db.redis.get("LTP:INDEX:INDIAVIX")
            
            nifty_fut_raw = await redis_db.redis.get("LTP:FUT:NIFTY:CURR")
            bank_fut_raw = await redis_db.redis.get("LTP:FUT:BANKNIFTY:CURR")
            
            nifty_tick = json.loads(nifty_spot_raw) if nifty_spot_raw else {}
            bank_tick = json.loads(bank_spot_raw) if bank_spot_raw else {}
            nifty_it_tick = json.loads(nifty_it_raw) if nifty_it_raw else {}
            
            nifty_spot = nifty_tick.get("ltp", 0)
            nifty_vol = nifty_tick.get("volume", 0)
            bank_spot = bank_tick.get("ltp", 0)
            bank_vol = bank_tick.get("volume", 0)
            it_spot = nifty_it_tick.get("ltp", 0)
            it_vol = nifty_it_tick.get("volume", 0)
            vix_spot = json.loads(vix_spot_raw).get("ltp", 0) if vix_spot_raw else 0
            
            nifty_fut = json.loads(nifty_fut_raw).get("ltp", nifty_spot) if nifty_fut_raw else nifty_spot
            bank_fut = json.loads(bank_fut_raw).get("ltp", bank_spot) if bank_fut_raw else bank_spot
            
            nifty_premium = nifty_fut - nifty_spot if nifty_spot > 0 else 0
            bank_premium = bank_fut - bank_spot if bank_spot > 0 else 0
            
            nifty_vwap_raw = await redis_db.redis.get("METRIC:VWAP:NIFTY50")
            bank_vwap_raw = await redis_db.redis.get("METRIC:VWAP:BANKNIFTY")
            nifty_vwap = json.loads(nifty_vwap_raw).get("vwap", nifty_spot) if nifty_vwap_raw else nifty_spot
            bank_vwap = json.loads(bank_vwap_raw).get("vwap", bank_spot) if bank_vwap_raw else bank_spot
            
            # Calculate Index Volume Deltas
            nifty_delta_vol = 0
            bank_delta_vol = 0
            it_delta_vol = 0
            if self.prev_state:
                nifty_delta_vol = nifty_vol - self.prev_state.get("indices", {}).get("NIFTY50", {}).get("volume", nifty_vol)
                bank_delta_vol = bank_vol - self.prev_state.get("indices", {}).get("BANKNIFTY", {}).get("volume", bank_vol)
                it_delta_vol = it_vol - self.prev_state.get("indices", {}).get("NIFTYIT", {}).get("volume", it_vol)

            # 4. Fetch Macro Context
            macro_state_raw = await redis_db.redis.get("MACRO_STATE")
            macro_state = json.loads(macro_state_raw) if macro_state_raw else {}
            
            # 5. Fetch Heavyweight Sector Health (Top Nifty & BankNifty drivers)
            heavyweight_symbols = [
                "HDFCBANK", "RELIANCE", "ICICIBANK", "INFY", "ITC", 
                "TCS", "LT", "AXISBANK", "KOTAKBANK", "SBIN",
                "BHARTIARTL", "HINDUNILVR", "BAJFINANCE", "MARUTI", "M&M",
                "HCLTECH", "TATAMOTORS", "SUNPHARMA", "ONGC", "NTPC",
                "POWERGRID", "TITAN", "ULTRACEMCO", "COALINDIA",
                "INDUSINDBK", "PNB", "BANKBARODA"
            ]
            heavyweights = {}
            for sym in heavyweight_symbols:
                tick_raw = await redis_db.redis.get(f"LTP:EQ:{sym}")
                if tick_raw:
                    tick = json.loads(tick_raw)
                    imb_raw = await redis_db.redis.get(f"METRIC:IMBALANCE:EQ:{sym}")
                    imb = json.loads(imb_raw).get("ratio", 1.0) if imb_raw else 1.0
                    vol = tick.get("volume", 0)
                    delta_vol = 0
                    if self.prev_state:
                        prev_h = self.prev_state.get("heavyweights", {}).get(sym, {})
                        delta_vol = vol - prev_h.get("volume", vol)

                    heavyweights[sym] = {
                        "ltp": tick.get("ltp", 0),
                        "volume": vol,
                        "delta_volume": delta_vol,
                        "imbalance": imb
                    }

            # 6. Fetch Open Positions (Portfolio State)
            paper_positions_raw = await redis_db.redis.get("PAPER_POSITIONS")
            portfolio = json.loads(paper_positions_raw) if paper_positions_raw else {}

            # 6.5 Fetch EOD and Institutional Data (FII/DII, Prev OHLC)
            fii_dii_raw = await redis_db.redis.get("FII_DII_DATA")
            fii_dii = json.loads(fii_dii_raw) if fii_dii_raw else {}
            
            prev_ohlc_raw = await redis_db.redis.get("PREV_DAY_OHLC")
            prev_ohlc = json.loads(prev_ohlc_raw) if prev_ohlc_raw else {}

            market_time = datetime.datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S')
            market_open = is_market_open()

            # 7. Fetch Option Chain Liquidity (Full ± 20 Strikes)
            option_chain = {"NIFTY": {}, "BANKNIFTY": {}}
            
            if nifty_spot > 0:
                nifty_atm = int(round(nifty_spot / 50.0)) * 50
                for step in range(-20, 21):
                    strike = nifty_atm + (step * 50)
                    for opt_type in ["CE", "PE"]:
                        sym = f"OPT:NIFTY:{strike}{opt_type}"
                        tick_raw = await redis_db.redis.get(f"LTP:{sym}")
                        if tick_raw:
                            tick = json.loads(tick_raw)
                            vol = tick.get("volume", 0)
                            oi = tick.get("oi", 0)
                            delta_vol = 0
                            delta_oi = 0
                            
                            # Retrieve Greeks from Greeks Engine
                            greek_raw = await redis_db.redis.get(f"GREEKS:{sym}")
                            greek_data = json.loads(greek_raw) if greek_raw else {}
                            iv = greek_data.get("iv", 0.0)
                            delta = greek_data.get("delta", 0.0)
                            gamma = greek_data.get("gamma", 0.0)
                            theta = greek_data.get("theta", 0.0)
                            
                            if self.prev_state:
                                prev_opt = self.prev_state.get("options_data", {}).get("chain", {}).get("NIFTY", {}).get(str(strike) + opt_type, {})
                                delta_vol = vol - prev_opt.get("volume", vol)
                                delta_oi = oi - prev_opt.get("oi", oi)
                            
                            option_chain["NIFTY"][str(strike) + opt_type] = {
                                "ltp": tick.get("ltp", 0),
                                "volume": vol,
                                "delta_volume": delta_vol,
                                "oi": oi,
                                "delta_oi": delta_oi,
                                "iv": iv,
                                "delta": delta,
                                "gamma": gamma,
                                "theta": theta
                            }
                            
            if bank_spot > 0:
                bank_atm = int(round(bank_spot / 100.0)) * 100
                for step in range(-20, 21):
                    strike = bank_atm + (step * 100)
                    for opt_type in ["CE", "PE"]:
                        sym = f"OPT:BANKNIFTY:{strike}{opt_type}"
                        tick_raw = await redis_db.redis.get(f"LTP:{sym}")
                        if tick_raw:
                            tick = json.loads(tick_raw)
                            vol = tick.get("volume", 0)
                            oi = tick.get("oi", 0)
                            delta_vol = 0
                            delta_oi = 0
                            
                            # Retrieve Greeks from Greeks Engine
                            greek_raw = await redis_db.redis.get(f"GREEKS:{sym}")
                            greek_data = json.loads(greek_raw) if greek_raw else {}
                            iv = greek_data.get("iv", 0.0)
                            delta = greek_data.get("delta", 0.0)
                            gamma = greek_data.get("gamma", 0.0)
                            theta = greek_data.get("theta", 0.0)
                            
                            if self.prev_state:
                                prev_opt = self.prev_state.get("options_data", {}).get("chain", {}).get("BANKNIFTY", {}).get(str(strike) + opt_type, {})
                                delta_vol = vol - prev_opt.get("volume", vol)
                                delta_oi = oi - prev_opt.get("oi", oi)

                            option_chain["BANKNIFTY"][str(strike) + opt_type] = {
                                "ltp": tick.get("ltp", 0),
                                "volume": vol,
                                "delta_volume": delta_vol,
                                "oi": oi,
                                "delta_oi": delta_oi,
                                "iv": iv,
                                "delta": delta,
                                "gamma": gamma,
                                "theta": theta
                            }

            # Construct the ultra-dense JSON prompt
            state = {
                "market_time": market_time,
                "is_market_open": market_open,
                "indices": {
                    "NIFTY50": {"ltp": nifty_spot, "volume": nifty_vol, "delta_volume": nifty_delta_vol, "vwap": nifty_vwap, "futures_premium": nifty_premium},
                    "BANKNIFTY": {"ltp": bank_spot, "volume": bank_vol, "delta_volume": bank_delta_vol, "vwap": bank_vwap, "futures_premium": bank_premium},
                    "NIFTYIT": {"ltp": it_spot, "volume": it_vol, "delta_volume": it_delta_vol},
                    "INDIAVIX": {"ltp": vix_spot}
                },
                "orderflow": {
                    "NIFTY_PCR": nifty_pcr,
                    "BANKNIFTY_PCR": bank_pcr,
                    "NIFTY_CVD": nifty_cvd,
                    "BANKNIFTY_CVD": bank_cvd,
                    "AD_RATIO": ad_ratio
                },
                "options_data": {
                    "NIFTY_GEX": float(nifty_gex_val),
                    "NIFTY_MAXPAIN": float(nifty_maxpain_val),
                    "BANKNIFTY_GEX": float(banknifty_gex_val),
                    "BANKNIFTY_MAXPAIN": float(banknifty_maxpain_val),
                    "chain": option_chain
                },
                "heavyweights": heavyweights,
                "macro": macro_state.get("markets", {}),
                "institutional": fii_dii,
                "prev_ohlc": prev_ohlc,
                "breaking_news": macro_state.get("news", {}).get("global_breaking", []),
                "indian_news": macro_state.get("news", {}).get("indian_markets", []),
                "portfolio": portfolio
            }

            self.prev_state = state
            
            # Use extremely compact JSON to minimize LLM token usage and latency
            return json.dumps(state, separators=(',', ':'))
            
        except Exception as e:
            logger.error(f"Failed to build market state: {e}")
            return "{}"

    async def get_system_prompt(self, is_open: bool = True) -> str:
        """
        Returns the system prompt instructing the LLM on how to behave based on market hours.
        """
        if not is_open:
            return (
                "You are an elite quantitative macro-analyst AI specializing in Indian Markets (Nifty/BankNifty). "
                "The market is currently CLOSED. Your task is to analyze the post-market/pre-market data provided in the state JSON. "
                "You must look at FII/DII data, global macro indices, breaking news, heavyweights performance, and option chain positioning (GEX/MaxPain) to form a bias for the next trading session. "
                "Your objective is to provide a concise, high-impact narrative and a market bias (BULLISH, BEARISH, or NEUTRAL). "
                "You must output EXACTLY a valid JSON object matching this schema, with NO markdown formatting or extra text: "
                '{"action": "ANALYSIS", "symbol": "MARKET_CLOSED", "confidence": <0-100>, "reason": "<high-impact analytical narrative summarizing key drivers for tomorrow>"}'
            )
            
        return (
            "You are an elite quantitative trading AI specializing in Nifty and BankNifty 0DTE options. "
            "You receive a real-time JSON market state representing Time, Volumes, Delta OI (Change in Open Interest), Delta Volumes (Spikes), VWAP, CVD, PCR, GEX, A/D Ratio, Heavyweight Order Imbalances, Futures Premium, Sectoral Synergy (Nifty IT vs BankNifty), and Macro data. "
            "Your objective is to identify high-probability scalps, avoid fake breakouts, and manage active portfolio risk. "
            "Rules: "
            "1. Price MUST be validated by Volume. If Index breaks out but Cumulative Volume Delta (CVD) and underlying heavyweight volumes are flat/negative, it is a FAKE BREAKOUT. DO NOT TRADE. "
            "2. BULLISH SETUP: If Price > VWAP with rising positive CVD, heavyweights showing positive order imbalance, and Call delta_oi is dropping (Short Covering), BUY a Call Option (CE). "
            "3. BEARISH SETUP: If Price < VWAP with falling negative CVD, heavyweights showing negative imbalance, and Put delta_oi is dropping (Long Unwinding), BUY a Put Option (PE). "
            "4. STRIKE SELECTION & GREEKS: Do NOT buy deep Out-of-The-Money (OTM) strikes. Always select At-The-Money (ATM) or In-The-Money (ITM). Evaluate Option Greeks for execution intelligence: Choose Calls (CE) with strong Delta when bullish, or Puts (PE) when bearish. Avoid strikes with high IV if IV is crashing, and beware of high Theta decay if market is chopping sideways. "
            "5. Time of Day: 9:15-10:30 is high volatility. 10:30-13:00 is chop zone (avoid trades). 13:00-15:00 is second half trend. "
            "6. If NIFTY_GEX is highly positive, expect mean reversion. If highly negative, expect high volatility trend continuation. "
            "7. Futures Premium: Tracks the spread between Futures and Spot price. A healthy Futures premium indicates bullish institutional flow. A sudden collapse in premium is a leading indicator of a sell-off. "
            "8. Sectoral Synergy: If NIFTY50 breaks out but NIFTYIT is collapsing, probability is lower. Ensure sectors align. "
            "9. IV Crush Detection: If the Implied Volatility (IV) on the active option is abnormally high (>30%) and INDIAVIX is dropping, DO NOT BUY. Anticipate IV Crush. "
            "10. NEWS OVERRIDE: Actively monitor 'indian_news' and 'breaking_news' for the latest headlines (we fetch the top 10 most recent global and domestic headlines). If multiple breaking news items form a catalyst that contradicts technical signals, you MUST prioritize the news impact. Avoid taking trades against the immediate news sentiment, and only trade in the direction of the catalyst (e.g., if news is intensely negative and data aligns bearish, prioritize Put (PE) execution). "
            "11. If Macro data indicates danger, exit longs instantly. "
            "12. You must output EXACTLY a valid JSON object matching this schema, with NO markdown formatting or extra text: "
            '{"action": "BUY"|"SELL"|"HOLD"|"CLOSE_ALL", "symbol": "<TICKER>", "qty": <int>, "confidence": <0-100>, "reason": "<short rationale>"}'
        )

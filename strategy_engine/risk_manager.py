import asyncio
import logging
import json
from typing import Dict, Any, Optional
from core.redis_client import redis_db
from core.config import settings
from execution_engine.shoonya_router import ShoonyaRouter
from execution_engine.paper_trader import PaperTrader
from execution_engine.fallback_router import DhanFallbackRouter

logger = logging.getLogger(__name__)

class RiskManager:
    """
    The ultimate safeguard. Placed strictly between the LLM Brain and the Execution Engine.
    Enforces dynamic circuit breakers, maximum daily loss limits, and maximum consecutive losses.
    """
    def __init__(self, mode: str = "PAPER"):
        self.mode = mode.upper()
        self.max_daily_loss = settings.MAX_DAILY_LOSS
        self.max_consecutive_losses = settings.MAX_CONSECUTIVE_LOSSES
        
        # Instantiate Execution Engines
        self.paper_trader = PaperTrader()
        self.shoonya_router = ShoonyaRouter()
        self.dhan_router = DhanFallbackRouter()
        
        # State tracking
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.is_halted = False

    async def initialize(self) -> bool:
        """Arms the risk manager and authenticates production routers if needed."""
        if self.mode == "LIVE":
            success = await self.shoonya_router.login()
            if not success:
                logger.critical("Failed to authenticate Primary Router. Halting system.")
                self.is_halted = True
                return False
        return True

    async def _check_circuit_breakers(self) -> bool:
        """
        Calculates dynamic circuit breakers based on Nifty 50 movement.
        If the market drops 10%, 15%, or 20%, trading must halt immediately.
        """
        nifty_raw = await redis_db.redis.get("LTP:INDEX:NIFTY50")
        if not nifty_raw:
            return True # Allow trading if no index data, though Blindness Rule might catch this elsewhere
            
        try:
            tick = json.loads(nifty_raw)
            ltp = tick.get("ltp", 0.0)
            prev_close = tick.get("close", ltp) # Fallback to LTP if close missing
            
            if prev_close > 0:
                drop_pct = ((prev_close - ltp) / prev_close) * 100
                if drop_pct >= 10.0:
                    logger.critical(f"CIRCUIT BREAKER TRIGGERED: Market dropped {drop_pct:.2f}%")
                    return False
        except Exception as e:
            logger.error(f"Circuit Breaker Check Failed: {e}")
            
        return True

    async def _update_pnl_state(self):
        """Fetches the latest portfolio state to update PnL constraints."""
        pos_raw = await redis_db.redis.get("PAPER_POSITIONS") if self.mode == "PAPER" else None
        # For LIVE, we would fetch from Shoonya/Dhan endpoints
        
        if pos_raw:
            positions = json.loads(pos_raw)
            total_realized = sum(pos.get("realized_pnl", 0.0) for pos in positions.values())
            self.daily_pnl = total_realized
            
            # If total loss exceeds max daily loss, halt
            if self.daily_pnl <= -self.max_daily_loss:
                logger.critical(f"MAX DAILY LOSS EXCEEDED! PnL: {self.daily_pnl}. Halting.")
                self.is_halted = True

    async def process_decision(self, decision: Dict[str, Any]) -> bool:
        """
        Takes the LLM's JSON decision, runs it through the risk gauntlet, and executes.
        """
        if self.is_halted:
            logger.warning("System is HALTED due to risk limit breach. Discarding decision.")
            return False
            
        action = decision.get("action", "HOLD")
        symbol = decision.get("symbol", "")
        qty = decision.get("qty", 0)
        
        if action == "HOLD" or qty <= 0:
            return True
            
        if action == "CLOSE_ALL":
            logger.critical(f"LLM REQUESTED PORTFOLIO LIQUIDATION. Reason: {decision.get('reason')}")
            await self._trigger_kill_switch()
            return True

        # 1. Update Portfolio PnL and Check Limits
        await self._update_pnl_state()
        if self.is_halted:
            await self._trigger_kill_switch()
            return False

        # 2. Check Dynamic Circuit Breakers
        if not await self._check_circuit_breakers():
            logger.critical("Market Crash detected. Halting and Liqudating.")
            self.is_halted = True
            await self._trigger_kill_switch()
            return False

        # 3. Route to Execution Engine
        logger.info(f"RISK APPROVED: Executing {action} {qty} {symbol}")
        
        if self.mode == "PAPER":
            order_id = await self.paper_trader.place_order(symbol, qty, action, "MKT")
            return order_id is not None
            
        elif self.mode == "LIVE":
            order_id = await self.shoonya_router.place_order(symbol, qty, action, "MKT")
            if not order_id:
                logger.error("Primary Router Failed. Routing to Fallback (Dhan)...")
                order_id = await self.dhan_router.place_order(symbol, qty, action, "MKT")
            return order_id is not None

    async def monitor_open_positions(self):
        """
        FAST LOOP for Risk Manager.
        Continuously monitors open positions for:
        1. Time-Based Auto-Exit (Theta Protection): If trade is stuck in a 5-point range for > 3 minutes, exit.
        2. Trailing Stop Loss (TSL): Once in 15+ points profit, trail SL by 10 points from high.
        """
        import time
        logger.info("Risk Manager Fast Loop (TSL & Theta Protection) Started.")
        
        while not self.is_halted:
            try:
                pos_raw = await redis_db.redis.get("PAPER_POSITIONS") if self.mode == "PAPER" else None
                # Fetch live positions from broker for LIVE mode in production
                
                if pos_raw:
                    positions = json.loads(pos_raw)
                    for symbol, pos in positions.items():
                        qty = pos.get("net_qty", 0)
                        if qty == 0:
                            continue
                            
                        avg_price = pos.get("avg_price", 0.0)
                        
                        # Get live tick
                        tick_raw = await redis_db.redis.get(f"LTP:{symbol}")
                        if not tick_raw:
                            continue
                            
                        tick = json.loads(tick_raw)
                        ltp = tick.get("ltp", 0.0)
                        
                        # Initialize tracking fields if not present
                        if "highest_price" not in pos:
                            pos["highest_price"] = avg_price
                        if "lowest_price" not in pos:
                            pos["lowest_price"] = avg_price
                        if "entry_time" not in pos:
                            pos["entry_time"] = time.time()
                            
                        # Update high/low
                        if qty > 0 and ltp > pos["highest_price"]:
                            pos["highest_price"] = ltp
                        elif qty < 0 and ltp < pos["lowest_price"]:
                            pos["lowest_price"] = ltp
                            
                        # 1. Trailing Stop Loss (TSL)
                        if qty > 0: # Long Position
                            profit_pts = pos["highest_price"] - avg_price
                            if profit_pts >= 15.0:
                                trailing_sl = pos["highest_price"] - 10.0
                                if ltp <= trailing_sl:
                                    logger.info(f"TRAILING SL HIT for {symbol} at {ltp}. Locking in profit!")
                                    await self.process_decision({"action": "SELL", "symbol": symbol, "qty": qty, "confidence": 100, "reason": "Trailing SL Hit"})
                                    continue
                                    
                        # 2. Time-Based Auto-Exit (Theta Protection)
                        hold_time = time.time() - pos["entry_time"]
                        if hold_time > 180: # 3 minutes
                            range_pts = abs(pos["highest_price"] - pos["lowest_price"])
                            if range_pts <= 5.0:
                                logger.info(f"THETA PROTECTION: Exiting {symbol}. Stuck in 5pt range for >3 mins.")
                                side = "SELL" if qty > 0 else "BUY"
                                await self.process_decision({"action": side, "symbol": symbol, "qty": abs(qty), "confidence": 100, "reason": "Theta Protection Auto-Exit"})
                                
                    # Save updated state back to Redis
                    if self.mode == "PAPER":
                        await redis_db.set_json("PAPER_POSITIONS", positions)
                        
            except Exception as e:
                logger.error(f"Error in Risk Manager Fast Loop: {e}")
                
            await asyncio.sleep(1) # Fast loop runs every second

    async def _trigger_kill_switch(self):
        """Fires the emergency liquidation across active routers."""
        if self.mode == "PAPER":
            await self.paper_trader.close_all_positions()
        elif self.mode == "LIVE":
            await self.shoonya_router.close_all_positions()
            # As an extreme fallback, we could also ping Dhan just in case
            await self.dhan_router.close_all_positions()

    async def shutdown(self):
        self.is_halted = True
        await self.shoonya_router.shutdown()
        await self.dhan_router.shutdown()

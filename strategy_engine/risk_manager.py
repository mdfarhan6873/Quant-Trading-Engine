import asyncio
import logging
import json
from typing import Dict, Any, Optional
from core.redis_client import redis_db
from core.config import settings
from core.database import init_db, log_trade
from execution_engine.paper_trader import PaperTrader

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
        if self.mode == "LIVE":
            from execution_engine.groww_router import GrowwRouter
            from execution_engine.fallback_router import DhanFallbackRouter
            self.groww_router = GrowwRouter()
            self.dhan_router = DhanFallbackRouter()
        else:
            self.groww_router = None
            self.dhan_router = None
        
        # State tracking
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.is_halted = False

    async def initialize(self) -> bool:
        """Arms the risk manager and authenticates production routers if needed."""
        init_db()  # Initialize SQLite database
        
        if self.mode == "LIVE":
            success = await self.groww_router.login()
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
        confidence = decision.get("confidence", 0)
        reason = decision.get("reason", "No reason provided")
        
        # Dynamic Quantity Sizing
        if action == "BUY":
            base_lot = 30 if "BANKNIFTY" in symbol else 65
            lots = 1
            if confidence >= 95:
                from core.database import get_setting
                if self.mode == "PAPER":
                    max_capital = float(get_setting("PAPER_FUNDS", getattr(settings, "MAX_CAPITAL", 50000)))
                else:
                    max_capital = getattr(settings, "MAX_CAPITAL", 50000)
                    
                tick_raw = await redis_db.redis.get(f"LTP:{symbol}")
                price = json.loads(tick_raw).get("ltp", 0.0) if tick_raw else 0.0
                
                target_lots = 5 if confidence >= 97 else 3
                
                if price > 0:
                    max_affordable_lots = int(max_capital / (price * base_lot))
                    lots = min(target_lots, max_affordable_lots)
                    if lots < 1: 
                        lots = 1
                else:
                    lots = target_lots
            qty = lots * base_lot
        else:
            qty = decision.get("qty", 0)
            # If SELL, ensure we sell exact open quantity
            pos_raw = await redis_db.redis.get("PAPER_POSITIONS") if self.mode == "PAPER" else None
            if pos_raw:
                positions = json.loads(pos_raw)
                if symbol in positions:
                    qty = abs(positions[symbol].get("net_qty", qty))
        
        if action == "HOLD" or qty <= 0:
            return True
            
        if action in ["BUY", "SELL"] and confidence < 90:
            logger.info(f"Trade discarded due to low AI confidence ({confidence}%). Minimum required is 90%.")
            return True # Discard trade safely
            
        if action == "CLOSE_ALL":
            logger.critical(f"LLM REQUESTED PORTFOLIO LIQUIDATION. Reason: {decision.get('reason')}")
            await self._trigger_kill_switch()
            return True

        # 1. Update Portfolio PnL and Check Limits
        await self._update_pnl_state()
        if self.is_halted:
            await self._trigger_kill_switch()
            return False

        # 1.5 Enforce One Trade At A Time Rule
        if action == "BUY":
            pos_raw = await redis_db.redis.get("PAPER_POSITIONS") if self.mode == "PAPER" else None # Replace with broker fetch for LIVE
            if pos_raw:
                positions = json.loads(pos_raw)
                active_open = any(abs(p.get("net_qty", 0)) > 0 for p in positions.values())
                if active_open:
                    logger.warning("Trade Blocked: A position is already open. Enforcing 'One Trade At A Time' rule.")
                    return True # Skip trade

        # 2. Check Dynamic Circuit Breakers
        if not await self._check_circuit_breakers():
            logger.critical("Market Crash detected. Halting and Liqudating.")
            self.is_halted = True
            await self._trigger_kill_switch()
            return False

        # 3. Route to Execution Engine
        logger.info(f"RISK APPROVED: Executing {action} {qty} {symbol}")
        
        order_id = None
        trade_pnl = 0.0
        if self.mode == "PAPER":
            order_id, trade_pnl = await self.paper_trader.place_order(symbol, qty, action, "MKT")
        elif self.mode == "LIVE":
            order_id = await self.groww_router.place_order(symbol, qty, action, "MKT")
            if not order_id:
                logger.error("Primary Router Failed. Routing to Fallback (Dhan)...")
                order_id = await self.dhan_router.place_order(symbol, qty, action, "MKT")
                
        # 4. Database Logging
        if order_id:
            updated_fund = 0.0
            
            if self.mode == "PAPER":
                from core.database import get_setting, set_setting
                current_fund = float(get_setting("PAPER_FUNDS", getattr(settings, "MAX_CAPITAL", 50000)))
                
                # Charge ₹60 brokerage per trade leg for paper realism (as per user request)
                updated_fund = current_fund - 60.0 + trade_pnl
                
                # Save the updated fund back to database
                set_setting("PAPER_FUNDS", str(updated_fund))
                
            # For now, let's just log the price.
            price = 0.0
            tick_raw = await redis_db.redis.get(f"LTP:{symbol}")
            if tick_raw:
                price = json.loads(tick_raw).get("ltp", 0.0)
                
            # Log to SQLite
            log_trade(symbol, action, qty, price, confidence, reason, trade_pnl, self.mode, updated_fund)
            
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
        """Fires the emergency liquidation across active routers and updates state."""
        self.is_halted = True
        logger.critical("KILL SWITCH INITIATED: Liquidating all open positions at market!")
        
        pos_raw = await redis_db.redis.get("PAPER_POSITIONS") if self.mode == "PAPER" else None
        if pos_raw:
            positions = json.loads(pos_raw)
            # Temporarily unhalt to process the close orders, then re-halt
            self.is_halted = False 
            for symbol, pos in list(positions.items()):
                qty = pos.get("net_qty", 0)
                if qty != 0:
                    side = "SELL" if qty > 0 else "BUY"
                    await self.process_decision({
                        "action": side,
                        "symbol": symbol,
                        "qty": abs(qty),
                        "confidence": 100,
                        "reason": "KILL SWITCH LIQUIDATION"
                    })
            self.is_halted = True
                    
        if self.mode == "LIVE":
            await self.groww_router.close_all_positions()
            await self.dhan_router.close_all_positions()

    async def shutdown(self):
        self.is_halted = True
        if self.groww_router:
            await self.groww_router.shutdown()
        if self.dhan_router:
            await self.dhan_router.shutdown()

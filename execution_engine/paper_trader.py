import asyncio
import logging
import json
import uuid
import time
from typing import Dict, Any, Optional
from core.redis_client import redis_db

logger = logging.getLogger(__name__)

class PaperTrader:
    """
    Paper Trading Execution Engine.
    Simulates real market fills by matching against live top-of-book (Bid/Ask).
    Incorporates slippage penalties and tracks simulated PnL in SQLite/CSV.
    """
    def __init__(self):
        self.open_positions: Dict[str, Dict[str, Any]] = {}
        self.trade_log = []
        self.slippage_bps = 2 # 2 basis points slippage for Nifty options
        
    async def get_live_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetches the absolute latest tick data from Redis."""
        tick_str = await redis_db.redis.get(f"LTP:{symbol}")
        if tick_str:
            return json.loads(tick_str)
        return None

    async def place_order(self, symbol: str, qty: int, side: str, order_type: str = "MKT", price: float = 0.0) -> Optional[str]:
        """
        Simulates an order execution based on REAL live order book depth.
        """
        tick = await self.get_live_quote(symbol)
        if not tick:
            logger.error(f"PaperTrade: Cannot execute {symbol}, no live tick available.")
            return None
            
        depth = tick.get("bid_ask", {})
        
        # Determine fill price
        fill_price = 0.0
        
        if side.upper() == "BUY":
            # Buy orders are filled at the best ASK
            asks = depth.get("asks", [])
            if asks:
                best_ask = asks[0].get("price", tick.get("ltp"))
            else:
                best_ask = tick.get("ltp")
                
            # Add slippage (buy higher)
            fill_price = best_ask * (1 + (self.slippage_bps / 10000))
            
        else:
            # Sell orders are filled at the best BID
            bids = depth.get("bids", [])
            if bids:
                best_bid = bids[0].get("price", tick.get("ltp"))
            else:
                best_bid = tick.get("ltp")
                
            # Add slippage (sell lower)
            fill_price = best_bid * (1 - (self.slippage_bps / 10000))
            
        fill_price = round(fill_price, 2)
        order_id = f"PAPER_{uuid.uuid4().hex[:8].upper()}"
        
        logger.info(f"PAPER FILL: {side} {qty} {symbol} @ ₹{fill_price} (Order: {order_id})")
        
        # Update internal positions
        await self._update_position(symbol, qty, side, fill_price)
        
        return order_id

    async def _update_position(self, symbol: str, qty: int, side: str, fill_price: float):
        """Maintains the simulated position book and calculates realized PnL."""
        if symbol not in self.open_positions:
            self.open_positions[symbol] = {"net_qty": 0, "avg_price": 0.0, "realized_pnl": 0.0}
            
        pos = self.open_positions[symbol]
        
        # Calculate new net qty and average price
        prev_qty = pos["net_qty"]
        prev_avg = pos["avg_price"]
        
        trade_qty = qty if side.upper() == "BUY" else -qty
        new_qty = prev_qty + trade_qty
        
        if prev_qty == 0:
            # New position
            pos["avg_price"] = fill_price
        elif (prev_qty > 0 and trade_qty > 0) or (prev_qty < 0 and trade_qty < 0):
            # Adding to position
            total_value = (abs(prev_qty) * prev_avg) + (abs(trade_qty) * fill_price)
            pos["avg_price"] = total_value / abs(new_qty)
        else:
            # Reducing or reversing position
            closed_qty = min(abs(prev_qty), abs(trade_qty))
            
            # Realized PnL Calculation
            if prev_qty > 0: # We were long, now selling
                pnl = (fill_price - prev_avg) * closed_qty
            else: # We were short, now buying
                pnl = (prev_avg - fill_price) * closed_qty
                
            pos["realized_pnl"] += pnl
            
            # Log the trade
            self.trade_log.append({
                "timestamp": time.time(),
                "symbol": symbol,
                "side": side,
                "qty": qty,
                "fill_price": fill_price,
                "realized_pnl": round(pnl, 2)
            })
            
            # If reversed
            if abs(trade_qty) > abs(prev_qty):
                pos["avg_price"] = fill_price

        pos["net_qty"] = new_qty
        
        # Save state to Redis so UI can render it
        await redis_db.set_json("PAPER_POSITIONS", self.open_positions)
        
    async def close_all_positions(self) -> bool:
        """Paper Trade Kill Switch"""
        logger.critical("PAPER KILL SWITCH: Liquidating all open positions at market!")
        tasks = []
        for symbol, pos in list(self.open_positions.items()):
            qty = pos["net_qty"]
            if qty != 0:
                side = "SELL" if qty > 0 else "BUY"
                tasks.append(self.place_order(symbol, abs(qty), side, "MKT"))
                
        if tasks:
            await asyncio.gather(*tasks)
            logger.critical("Paper Portfolio Liquidated.")
        return True

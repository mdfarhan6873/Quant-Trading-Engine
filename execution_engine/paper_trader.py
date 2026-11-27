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
        self.slippage_bps = 2  # 2 basis points slippage for Nifty options

    async def hydrate_from_redis(self):
        """Synchronizes in-memory position book with Redis PAPER_POSITIONS so restarts preserve entry avg_price & PnL."""
        saved = await redis_db.get_json("PAPER_POSITIONS")
        if isinstance(saved, dict):
            self.open_positions = saved
        
    async def get_live_quote(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetches the absolute latest tick data from Redis, normalizing optional LTP:/OPT: prefixes."""
        clean_sym = symbol[4:] if symbol.startswith("LTP:") else symbol
        candidates = [f"LTP:{clean_sym}"]
        if not clean_sym.startswith(("OPT:", "INDEX:", "FUT:", "EQ:")):
            if clean_sym.startswith("BANKNIFTY") and (clean_sym.endswith("CE") or clean_sym.endswith("PE")):
                strike_part = clean_sym[len("BANKNIFTY"):]
                candidates.append(f"LTP:OPT:BANKNIFTY:{strike_part}")
            elif clean_sym.startswith("NIFTY") and (clean_sym.endswith("CE") or clean_sym.endswith("PE")):
                strike_part = clean_sym[len("NIFTY"):]
                candidates.append(f"LTP:OPT:NIFTY:{strike_part}")
        for key in candidates:
            tick = await redis_db.get_json(key)
            if tick:
                return tick
        return None

    @staticmethod
    def _extract_top_of_book(tick: Dict[str, Any], side: str) -> float:
        """Extracts best ask (for BUY) or best bid (for SELL) across Upstox/NSE/legacy depth schemas."""
        ltp = float(tick.get("ltp") or 0.0)
        depth = tick.get("bid_ask") or {}
        levels = depth.get("depth") if isinstance(depth, dict) else None

        if side.upper() == "BUY":
            direct_ask = float(tick.get("ask") or 0.0)
            if direct_ask > 0:
                return direct_ask
            if isinstance(levels, list) and levels:
                lvl_ask = float(levels[0].get("askP") or levels[0].get("askPrice") or 0.0)
                if lvl_ask > 0:
                    return lvl_ask
            asks = depth.get("asks", []) if isinstance(depth, dict) else []
            if asks:
                legacy_ask = float(asks[0].get("price") or 0.0)
                if legacy_ask > 0:
                    return legacy_ask
            return ltp

        direct_bid = float(tick.get("bid") or 0.0)
        if direct_bid > 0:
            return direct_bid
        if isinstance(levels, list) and levels:
            lvl_bid = float(levels[0].get("bidP") or levels[0].get("bidPrice") or 0.0)
            if lvl_bid > 0:
                return lvl_bid
        bids = depth.get("bids", []) if isinstance(depth, dict) else []
        if bids:
            legacy_bid = float(bids[0].get("price") or 0.0)
            if legacy_bid > 0:
                return legacy_bid
        return ltp

    async def place_order(self, symbol: str, qty: int, side: str, order_type: str = "MKT", price: float = 0.0) -> tuple[Optional[str], float]:
        """
        Simulates an order execution based on REAL live order book depth.
        Enforces strict Long-Only Option Buying protection so SELL orders never flip a long position into naked short.
        Returns (order_id, realized_pnl_for_this_trade).
        """
        tick = await self.get_live_quote(symbol)
        if not tick:
            logger.error(f"PaperTrade: Cannot execute {symbol}, no live tick available.")
            return None, 0.0

        # Always synchronize with Redis PAPER_POSITIONS before evaluating fills or exits
        await self.hydrate_from_redis()

        side_u = side.upper()
        if side_u == "SELL":
            existing_qty = int((self.open_positions.get(symbol) or {}).get("net_qty", 0) or 0)
            if existing_qty <= 0:
                logger.warning(f"PaperTrade Blocked: Cannot SELL {symbol} when position is flat/non-long (net_qty={existing_qty}).")
                return None, 0.0
            if qty > existing_qty:
                logger.warning(f"PaperTrade Clamped: Reducing SELL {symbol} qty {qty} -> {existing_qty} to avoid accidental short flip.")
                qty = existing_qty

        ltp = float(tick.get("ltp") or price or 0.0)
        if side_u == "BUY":
            best_ask = self._extract_top_of_book(tick, "BUY") or ltp
            fill_price = best_ask * (1 + (self.slippage_bps / 10000))
        else:
            best_bid = self._extract_top_of_book(tick, "SELL") or ltp
            fill_price = best_bid * (1 - (self.slippage_bps / 10000))

        fill_price = round(fill_price, 2)
        order_id = f"PAPER_{uuid.uuid4().hex[:8].upper()}"

        logger.info(f"PAPER FILL: {side_u} {qty} {symbol} @ ₹{fill_price} (Order: {order_id})")

        # Update internal positions
        trade_pnl = await self._update_position(symbol, qty, side_u, fill_price)

        return order_id, trade_pnl

    async def _update_position(self, symbol: str, qty: int, side: str, fill_price: float) -> float:
        """Maintains the simulated position book and calculates realized PnL. Returns the PnL of this specific trade."""
        if symbol not in self.open_positions:
            self.open_positions[symbol] = {
                "net_qty": 0,
                "avg_price": 0.0,
                "current_ltp": fill_price,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "entry_time": time.time(),
            }

        pos = self.open_positions[symbol]

        # Calculate new net qty and average price
        prev_qty = int(pos.get("net_qty", 0) or 0)
        prev_avg = float(pos.get("avg_price", 0.0) or 0.0)

        trade_qty = qty if side.upper() == "BUY" else -qty
        new_qty = prev_qty + trade_qty

        trade_pnl = 0.0

        if prev_qty == 0:
            # New position
            pos["avg_price"] = fill_price
            pos["entry_time"] = time.time()
            pos["highest_price"] = fill_price
            pos["lowest_price"] = fill_price
        elif (prev_qty > 0 and trade_qty > 0) or (prev_qty < 0 and trade_qty < 0):
            # Adding to position
            total_value = (abs(prev_qty) * prev_avg) + (abs(trade_qty) * fill_price)
            pos["avg_price"] = total_value / abs(new_qty)
        else:
            # Reducing or closing position
            closed_qty = min(abs(prev_qty), abs(trade_qty))

            # Realized PnL Calculation
            if prev_qty > 0: # We were long, now selling
                pnl = (fill_price - prev_avg) * closed_qty
            else: # We were short, now buying
                pnl = (prev_avg - fill_price) * closed_qty

            trade_pnl = round(pnl, 2)
            pos["realized_pnl"] = round(float(pos.get("realized_pnl", 0.0) or 0.0) + trade_pnl, 2)

            # If reversed
            if abs(trade_qty) > abs(prev_qty):
                pos["avg_price"] = fill_price

        pos["net_qty"] = new_qty
        pos["current_ltp"] = fill_price
        pos["unrealized_pnl"] = 0.0 if new_qty == 0 else round((fill_price - pos["avg_price"]) * new_qty, 2)
        pos["updated_at"] = time.time()

        # Log the trade internally
        self.trade_log.append({
            "timestamp": time.time(),
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "fill_price": fill_price,
            "realized_pnl": round(trade_pnl, 2),
        })

        # Remove flat positions cleanly so Redis never retains zero-qty ghosts
        if new_qty == 0:
            self.open_positions.pop(symbol, None)

        # Save state to Redis so UI can render it
        await redis_db.set_json("PAPER_POSITIONS", self.open_positions)
        return trade_pnl
        
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

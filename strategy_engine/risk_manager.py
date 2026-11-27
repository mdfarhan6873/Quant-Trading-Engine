import asyncio
import datetime
import json
import logging
import sqlite3
import time
from typing import Any, Dict, Optional

import pytz

from core.config import settings
from core.database import DB_PATH, init_db, log_trade
from core.redis_client import redis_db
from execution_engine.paper_trader import PaperTrader

logger = logging.getLogger(__name__)


class RiskManager:
    """
    The ultimate safeguard placed strictly between the LLM Brain and Execution Engine.
    Enforces:
    - Patience Protocol (max 3 trades/day persisted in SQLite across restarts, 20m cooldown)
    - Minimum Conviction floor (configurable PAPER floor >=70%, strict LIVE floor >=90%)
    - One position at a time + Hard Stop Loss (-25% / -30pt) + Trailing SL (+15/-10) + Theta Guard
    - Automatic episode learning into QuantEpisodicMemoryRAG when positions close
    """

    def __init__(self, mode: str = "PAPER"):
        self.mode = mode.upper()
        self.max_daily_loss = settings.MAX_DAILY_LOSS
        self.max_consecutive_losses = settings.MAX_CONSECUTIVE_LOSSES

        # Execution Engines
        self.paper_trader = PaperTrader()
        if self.mode == "LIVE":
            from execution_engine.fallback_router import DhanFallbackRouter
            from execution_engine.groww_router import GrowwRouter

            self.groww_router = GrowwRouter()
            self.dhan_router = DhanFallbackRouter()
        else:
            self.groww_router = None
            self.dhan_router = None

        # State tracking & async re-entrancy guard between Slow Loop (Brain) & Fast Loop (1s SL Monitor)
        self._exec_lock = asyncio.Lock()
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.is_halted = False

        # Anti-Overtrading & Patience Engine State
        self.max_daily_trades = 3
        self.daily_trades_count = 0
        self.current_trade_date = None
        self.last_trade_closed_time = 0.0
        self.post_trade_cooldown_seconds = 1200.0  # 20-minute mandatory observation cooldown

    async def initialize(self) -> bool:
        """Arms the risk manager, hydrates open Paper positions & today's SQLite counts, and authenticates routers."""
        init_db()

        tz = pytz.timezone("Asia/Kolkata")
        today = datetime.datetime.now(tz).date()
        self.current_trade_date = today
        self._restore_daily_counters_from_sqlite(today.isoformat())

        if self.mode == "PAPER":
            await self.paper_trader.hydrate_from_redis()
            # Clean up any zero-qty phantom entries leftover in PAPER_POSITIONS if clean
            for sym, p in list(self.paper_trader.open_positions.items()):
                if int(p.get("net_qty", 0) or 0) == 0:
                    self.paper_trader.open_positions.pop(sym, None)
            await redis_db.set_json("PAPER_POSITIONS", self.paper_trader.open_positions)

        if self.mode == "LIVE":
            success = await self.groww_router.login()
            if not success:
                logger.critical("Failed to authenticate Primary Router. Halting system.")
                self.is_halted = True
                return False

        await self.sync_execution_state()
        return True

    def _restore_daily_counters_from_sqlite(self, today_iso: str):
        """Restores today's executed BUY count, realized PnL, and last SELL cooldown across server restarts."""
        try:
            conn = sqlite3.connect(DB_PATH, timeout=5.0)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT action, pnl, timestamp FROM trade_logs WHERE timestamp LIKE ? AND mode = ? ORDER BY id ASC",
                (f"{today_iso}%", self.mode),
            )
            rows = cursor.fetchall()
            conn.close()

            buy_count = 0
            realized_pnl = 0.0
            last_sell_ts = 0.0
            for act, pnl_val, ts_str in rows:
                if act == "BUY":
                    buy_count += 1
                elif act == "SELL":
                    realized_pnl += float(pnl_val or 0.0)
                    try:
                        last_sell_ts = datetime.datetime.fromisoformat(ts_str).timestamp()
                    except Exception:
                        pass

            self.daily_trades_count = buy_count
            self.daily_pnl = round(realized_pnl, 2)
            if last_sell_ts > 0:
                self.last_trade_closed_time = last_sell_ts
            if self.daily_pnl <= -self.max_daily_loss:
                self.is_halted = True
                logger.critical(f"MAX DAILY LOSS ALREADY EXCEEDED ({self.daily_pnl}). Halted.")
        except Exception as e:
            logger.debug(f"Could not restore daily counters from SQLite: {e}")

    async def sync_execution_state(self) -> Dict[str, Any]:
        """Persists live execution & risk-budget state to EXECUTION:STATE:LATEST in Redis."""
        from core.database import get_setting

        pos_raw = await redis_db.redis.get("PAPER_POSITIONS") if self.mode == "PAPER" else None
        positions = json.loads(pos_raw) if pos_raw else {}

        open_positions = {}
        total_realized = 0.0
        total_unrealized = 0.0
        for sym, pos in positions.items():
            net_qty = int(pos.get("net_qty", 0) or 0)
            total_realized += float(pos.get("realized_pnl", 0.0) or 0.0)
            if net_qty != 0:
                total_unrealized += float(pos.get("unrealized_pnl", 0.0) or 0.0)
                open_positions[sym] = pos

        if self.mode == "PAPER":
            capital_available = float(get_setting("PAPER_FUNDS", getattr(settings, "MAX_CAPITAL", 50000)))
        else:
            capital_available = float(getattr(settings, "MAX_CAPITAL", 50000))

        lot_nifty_raw = await redis_db.redis.get("SYSTEM:LOT:NIFTY")
        lot_bank_raw = await redis_db.redis.get("SYSTEM:LOT:BANKNIFTY")
        cooldown_rem = 0
        if self.last_trade_closed_time > 0:
            cooldown_rem = max(0, int(self.post_trade_cooldown_seconds - (time.time() - self.last_trade_closed_time)))

        exec_state = {
            "mode": self.mode,
            "is_halted": self.is_halted,
            "open_positions": open_positions,
            "realized_pnl_today": round(self.daily_pnl if abs(self.daily_pnl) > 0 else total_realized, 2),
            "unrealized_pnl": round(total_unrealized, 2),
            "capital_available": round(capital_available, 2),
            "trades_executed_today": self.daily_trades_count,
            "max_daily_trades": self.max_daily_trades,
            "cooldown_remaining_seconds": cooldown_rem,
            "active_lot_size_nifty": int(lot_nifty_raw) if lot_nifty_raw else 65,
            "active_lot_size_banknifty": int(lot_bank_raw) if lot_bank_raw else 30,
            "updated_at": time.time(),
        }
        await redis_db.set_json("EXECUTION:STATE:LATEST", exec_state)
        return exec_state

    async def _check_circuit_breakers(self) -> bool:
        """Halts immediately if Nifty 50 drops >=10% intraday."""
        nifty_raw = await redis_db.redis.get("LTP:INDEX:NIFTY50")
        if not nifty_raw:
            return True

        try:
            tick = json.loads(nifty_raw)
            ltp = float(tick.get("ltp", 0.0) or 0.0)
            prev_close = float(tick.get("close", ltp) or ltp)
            if prev_close > 0:
                drop_pct = ((prev_close - ltp) / prev_close) * 100.0
                if drop_pct >= 10.0:
                    logger.critical(f"CIRCUIT BREAKER TRIGGERED: Market dropped {drop_pct:.2f}%")
                    return False
        except Exception as e:
            logger.error(f"Circuit Breaker Check Failed: {e}")

        return True

    async def _update_pnl_state(self):
        """Enforces MAX_DAILY_LOSS across closed + active positions."""
        if self.daily_pnl <= -self.max_daily_loss:
            logger.critical(f"MAX DAILY LOSS EXCEEDED! PnL: {self.daily_pnl}. Halting.")
            self.is_halted = True

    async def process_decision(self, decision: Dict[str, Any]) -> bool:
        """Thread/task-safe entrypoint serialized through `_exec_lock`."""
        async with self._exec_lock:
            return await self._process_decision_unlocked(decision)

    async def _process_decision_unlocked(self, decision: Dict[str, Any]) -> bool:
        if self.is_halted:
            logger.warning("System is HALTED due to risk limit breach. Discarding decision.")
            return False

        raw_action = str(decision.get("action", "OBSERVE")).upper()
        symbol = str(decision.get("symbol") or "").strip()
        confidence = float(decision.get("confidence", 0) or 0)
        reason = decision.get("reason", "No reason provided")
        risk_controls = decision.setdefault("risk_controls", {})

        tz = pytz.timezone("Asia/Kolkata")
        today = datetime.datetime.now(tz).date()
        if self.current_trade_date != today:
            self.current_trade_date = today
            self.daily_trades_count = 0
            self.daily_pnl = 0.0
            logger.info(f"Daily Trade Counter reset for session: {today}")

        if raw_action in ["OBSERVE", "HOLD", "NO_TRADE", "PRESERVE_CAPITAL", "ANALYSIS", "MARKET_CLOSED"]:
            risk_controls["execution_authorized"] = False
            logger.debug(f"Patience Engine: Maintaining {raw_action} state. Zero capital committed.")
            return True

        if raw_action == "CLOSE_ALL":
            logger.critical(f"LLM REQUESTED PORTFOLIO LIQUIDATION. Reason: {reason}")
            await self._trigger_kill_switch_unlocked()
            await self.sync_execution_state()
            return True

        is_entry = raw_action in ["BUY", "ENTER_CALL", "ENTER_PUT"]
        is_exit = raw_action in ["SELL", "EXIT", "REDUCE"]
        action = "BUY" if is_entry else "SELL" if is_exit else "HOLD"

        if is_entry:
            crit_failures = int(
                decision.get("factor_audit", {})
                .get("summary_metrics", {})
                .get("critical_failures", 0)
                or 0
            )
            if crit_failures > 0:
                risk_controls["execution_authorized"] = False
                logger.warning(f"CONTRACT 1 VETO: {crit_failures} critical failure(s). Blocking entry.")
                await self.sync_execution_state()
                return True

            if self.daily_trades_count >= self.max_daily_trades:
                risk_controls["execution_authorized"] = False
                logger.warning(f"ANTI-OVERTRADING SHIELD: {self.daily_trades_count}/{self.max_daily_trades} trades hit.")
                await self.sync_execution_state()
                return True

            now_ts = time.time()
            elapsed_since_last_exit = now_ts - self.last_trade_closed_time
            if self.last_trade_closed_time > 0 and elapsed_since_last_exit < self.post_trade_cooldown_seconds:
                remaining_cooldown = int(self.post_trade_cooldown_seconds - elapsed_since_last_exit)
                risk_controls["execution_authorized"] = False
                risk_controls["post_trade_cooldown_active"] = True
                logger.warning(f"PATIENCE ENGINE LOCKOUT: Cooldown active ({remaining_cooldown}s remaining).")
                await self.sync_execution_state()
                return True

            min_conf = 90 if self.mode == "LIVE" else max(70, int(getattr(settings, "LLM_MIN_CONFIDENCE", 78) or 78))
            if confidence < min_conf:
                risk_controls["execution_authorized"] = False
                logger.info(f"Patience Protocol: Low AI confidence ({confidence}% < {min_conf}%).")
                await self.sync_execution_state()
                return True

        # Auto-resolve ATM option symbol if missing
        if action == "BUY" and (not symbol or symbol in ("NIFTY50", "BANKNIFTY", "NIFTY")):
            idx_key = "BANKNIFTY" if "BANK" in (decision.get("instrument", "") + symbol).upper() else "NIFTY"
            spot_key = "LTP:INDEX:NIFTYBANK" if idx_key == "BANKNIFTY" else "LTP:INDEX:NIFTY50"
            step = 100 if idx_key == "BANKNIFTY" else 50
            spot_tick = await redis_db.get_json(spot_key)
            spot_px = float((spot_tick or {}).get("ltp") or 0.0)
            if spot_px > 0:
                atm = int(round(spot_px / float(step))) * step
                opt_side = "PE" if raw_action == "ENTER_PUT" else "CE"
                symbol = f"OPT:{idx_key}:{atm}{opt_side}"
                decision["symbol"] = symbol

        if action == "BUY":
            if "BANKNIFTY" in symbol:
                lot_raw = await redis_db.redis.get("SYSTEM:LOT:BANKNIFTY")
                base_lot = int(lot_raw) if lot_raw else 30
            else:
                lot_raw = await redis_db.redis.get("SYSTEM:LOT:NIFTY")
                base_lot = int(lot_raw) if lot_raw else 65
            lots = max(1, int(decision.get("lots") or decision.get("qty") or 1))
            if confidence >= 95:
                from core.database import get_setting

                max_capital = float(
                    get_setting("PAPER_FUNDS", getattr(settings, "MAX_CAPITAL", 50000))
                    if self.mode == "PAPER"
                    else getattr(settings, "MAX_CAPITAL", 50000)
                )
                tick = await self.paper_trader.get_live_quote(symbol)
                price = float(tick.get("ltp", 0.0) or 0.0) if tick else 0.0
                target_lots = 5 if confidence >= 97 else 3
                if price > 0:
                    max_affordable_lots = int(max_capital / (price * base_lot))
                    lots = max(1, min(target_lots, max_affordable_lots))
                else:
                    lots = target_lots
            qty = lots * base_lot
        elif action == "SELL":
            qty = 0
            if self.mode == "PAPER":
                pos_raw = await redis_db.redis.get("PAPER_POSITIONS")
                positions = json.loads(pos_raw) if pos_raw else {}
                if symbol and symbol in positions and int(positions[symbol].get("net_qty", 0) or 0) != 0:
                    qty = abs(int(positions[symbol]["net_qty"]))
                elif not symbol:
                    for sym_k, p_val in positions.items():
                        nq = int(p_val.get("net_qty", 0) or 0)
                        if nq != 0:
                            symbol = sym_k
                            qty = abs(nq)
                            break
            else:
                qty = int(decision.get("qty", 0) or 0)
        else:
            qty = 0

        if action == "HOLD" or qty <= 0 or not symbol:
            risk_controls["execution_authorized"] = False
            return True

        await self._update_pnl_state()
        if self.is_halted:
            risk_controls["execution_authorized"] = False
            await self._trigger_kill_switch_unlocked()
            await self.sync_execution_state()
            return False

        if action == "BUY":
            pos_raw = await redis_db.redis.get("PAPER_POSITIONS") if self.mode == "PAPER" else None
            if pos_raw:
                positions = json.loads(pos_raw)
                if any(abs(int(p.get("net_qty", 0) or 0)) > 0 for p in positions.values()):
                    risk_controls["execution_authorized"] = False
                    logger.warning("Trade Blocked: Open position active ('One Trade At A Time' rule).")
                    await self.sync_execution_state()
                    return True

        if not await self._check_circuit_breakers():
            logger.critical("Market Crash detected. Halting and Liquidating.")
            self.is_halted = True
            risk_controls["execution_authorized"] = False
            await self._trigger_kill_switch_unlocked()
            await self.sync_execution_state()
            return False

        risk_controls["execution_authorized"] = True
        risk_controls["max_lots_permitted"] = max(1, qty)
        logger.info(f"RISK APPROVED: Executing {action} {qty} {symbol}")

        order_id = None
        trade_pnl = 0.0
        if self.mode == "PAPER":
            order_id, trade_pnl = await self.paper_trader.place_order(symbol, qty, action, "MKT")
            # Remove closed zero-qty keys cleanly so stale monitor loops cannot revive them
            for s_k in list(self.paper_trader.open_positions.keys()):
                if int(self.paper_trader.open_positions[s_k].get("net_qty", 0) or 0) == 0:
                    self.paper_trader.open_positions.pop(s_k, None)
            await redis_db.set_json("PAPER_POSITIONS", self.paper_trader.open_positions)
        elif self.mode == "LIVE":
            order_id = await self.groww_router.place_order(symbol, qty, action, "MKT")
            if not order_id and getattr(settings, "DHAN_ACCESS_TOKEN", ""):
                logger.error("Primary Router Failed. Routing to Fallback (Dhan)...")
                order_id = await self.dhan_router.place_order(symbol, qty, action, "MKT")

        if order_id:
            if action == "BUY":
                self.daily_trades_count += 1
                logger.info(f"Trade Execution Count: {self.daily_trades_count}/{self.max_daily_trades} for today.")
            elif action == "SELL":
                self.last_trade_closed_time = time.time()
                self.daily_pnl = round(self.daily_pnl + trade_pnl, 2)
                logger.info(f"Position Closed (PnL: ₹{trade_pnl:+.2f}). 20-minute observation lockout activated.")
                await self._record_closed_episode(raw_action, trade_pnl, reason)

            updated_fund = 0.0
            if self.mode == "PAPER":
                from core.database import get_setting, set_setting

                current_fund = float(get_setting("PAPER_FUNDS", getattr(settings, "MAX_CAPITAL", 50000)))
                updated_fund = round(current_fund - 60.0 + trade_pnl, 2)
                set_setting("PAPER_FUNDS", str(updated_fund))

            fill_price = 0.0
            if self.mode == "PAPER" and self.paper_trader.trade_log:
                fill_price = float(self.paper_trader.trade_log[-1].get("fill_price", 0.0) or 0.0)
            if fill_price <= 0:
                tick = await self.paper_trader.get_live_quote(symbol)
                fill_price = float(tick.get("ltp", 0.0) or 0.0) if tick else 0.0

            log_trade(symbol, action, qty, fill_price, int(confidence), reason, trade_pnl, self.mode, updated_fund)

        await self.sync_execution_state()
        return order_id is not None

    async def _record_closed_episode(self, action: str, pnl: float, lesson: str):
        """Records completed trade outcomes into Quant RAG SQLite vector memory for continuous adaptation."""
        try:
            from strategy_engine.episodic_memory import QuantEpisodicMemoryRAG

            state_dict = await redis_db.get_json("FULL_MARKET_STATE") or {}
            if state_dict:
                QuantEpisodicMemoryRAG().record_episode_outcome(state_dict, action, pnl, lesson[:220])
        except Exception as e:
            logger.debug(f"Could not record closed episode: {e}")

    async def monitor_open_positions(self):
        """
        1-second Fast Risk Loop monitoring open positions for:
        1. Hard Stop Loss (-25% or -30 pts below avg entry once held >= 10s)
        2. Trailing Stop Loss (+15pt activation / -10pt trail from high)
        3. Time-Based Theta Protection (exit only if held >15 mins in narrow <=6pt stagnation)
        """
        logger.info("Risk Manager Fast Loop (Hard SL, TSL & Theta Protection) Started.")

        while not self.is_halted:
            try:
                if self.mode == "PAPER":
                    exit_request = None
                    updated_positions = None

                    async with self._exec_lock:
                        pos_raw = await redis_db.redis.get("PAPER_POSITIONS")
                        positions = json.loads(pos_raw) if pos_raw else {}

                        for symbol, pos in list(positions.items()):
                            qty = int(pos.get("net_qty", 0) or 0)
                            if qty == 0:
                                positions.pop(symbol, None)
                                continue

                            avg_price = float(pos.get("avg_price", 0.0) or 0.0)
                            if avg_price <= 0:
                                continue

                            tick = await self.paper_trader.get_live_quote(symbol)
                            if not tick:
                                continue

                            ltp = float(tick.get("ltp", 0.0) or 0.0)
                            if ltp <= 0:
                                continue

                            pos["current_ltp"] = ltp
                            pos["unrealized_pnl"] = round((ltp - avg_price) * qty, 2)
                            pos.setdefault("highest_price", avg_price)
                            pos.setdefault("lowest_price", avg_price)
                            pos.setdefault("entry_time", time.time())

                            if ltp > pos["highest_price"]:
                                pos["highest_price"] = ltp
                            if ltp < pos["lowest_price"]:
                                pos["lowest_price"] = ltp

                            hold_time = time.time() - float(pos["entry_time"])
                            side = "SELL" if qty > 0 else "BUY"

                            # 1. Hard Stop Loss (protect capital unconditionally against adverse spikes)
                            if qty > 0:
                                hard_sl = round(max(avg_price * 0.75, avg_price - 30.0), 2)
                                pos["stop_loss"] = hard_sl
                                if hold_time >= 10.0 and ltp <= hard_sl:
                                    logger.warning(f"HARD SL HIT for {symbol} @ {ltp} (SL ₹{hard_sl})")
                                    exit_request = {
                                        "action": side,
                                        "symbol": symbol,
                                        "qty": abs(qty),
                                        "confidence": 100,
                                        "reason": f"Hard Protective SL Hit (₹{ltp} <= ₹{hard_sl})",
                                    }
                                    break

                                # 2. Trailing Stop Loss (TSL)
                                profit_pts = float(pos["highest_price"]) - avg_price
                                if profit_pts >= 15.0:
                                    trailing_sl = round(float(pos["highest_price"]) - 10.0, 2)
                                    pos["trailing_sl"] = trailing_sl
                                    if ltp <= trailing_sl:
                                        logger.info(f"TRAILING SL HIT for {symbol} at {ltp}. Locking in profit!")
                                        exit_request = {
                                            "action": side,
                                            "symbol": symbol,
                                            "qty": abs(qty),
                                            "confidence": 100,
                                            "reason": f"Trailing SL Hit (₹{ltp} <= ₹{trailing_sl})",
                                        }
                                        break

                            # 3. Time-Based Auto-Exit (Theta Protection — only after 15 mins of genuine sideways stagnation)
                            if hold_time > 900.0:
                                range_pts = abs(float(pos["highest_price"]) - float(pos["lowest_price"]))
                                net_move = abs(ltp - avg_price)
                                if range_pts <= 6.0 and net_move <= 4.0:
                                    logger.info(
                                        f"THETA PROTECTION: Exiting {symbol}. Stagnant for {int(hold_time)}s (range={range_pts:.1f}pt, move={net_move:.1f}pt)."
                                    )
                                    exit_request = {
                                        "action": side,
                                        "symbol": symbol,
                                        "qty": abs(qty),
                                        "confidence": 100,
                                        "reason": "Theta Protection Auto-Exit (>15m stagnant option)",
                                    }
                                    break

                        if exit_request is None and positions:
                            updated_positions = positions
                            await redis_db.set_json("PAPER_POSITIONS", updated_positions)

                    # Execute exit OUTSIDE position snapshot write so stale quantities never overwrite Redis!
                    if exit_request is not None:
                        await self.process_decision(exit_request)
                    elif updated_positions is not None:
                        await self.sync_execution_state()

            except Exception as e:
                logger.error(f"Error in Risk Manager Fast Loop: {e}")

            await asyncio.sleep(1.0)

    async def _trigger_kill_switch(self):
        async with self._exec_lock:
            await self._trigger_kill_switch_unlocked()

    async def _trigger_kill_switch_unlocked(self):
        """Fires emergency liquidation safely without racing or deadlocking `_exec_lock`."""
        self.is_halted = True
        logger.critical("KILL SWITCH INITIATED: Liquidating all open positions at market!")

        if self.mode == "PAPER":
            pos_raw = await redis_db.redis.get("PAPER_POSITIONS")
            if pos_raw:
                positions = json.loads(pos_raw)
                self.is_halted = False
                for symbol, pos in list(positions.items()):
                    qty = int(pos.get("net_qty", 0) or 0)
                    if qty != 0:
                        side = "SELL" if qty > 0 else "BUY"
                        await self._process_decision_unlocked({
                            "action": side,
                            "symbol": symbol,
                            "qty": abs(qty),
                            "confidence": 100,
                            "reason": "KILL SWITCH LIQUIDATION",
                        })
                self.is_halted = True

        elif self.mode == "LIVE":
            if self.groww_router:
                await self.groww_router.close_all_positions()
            if self.dhan_router:
                await self.dhan_router.close_all_positions()

        await self.sync_execution_state()

    async def shutdown(self):
        self.is_halted = True
        if self.groww_router:
            await self.groww_router.shutdown()
        if self.dhan_router:
            await self.dhan_router.shutdown()

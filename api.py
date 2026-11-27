import asyncio
from datetime import datetime
import json
import logging
import os
import sqlite3
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from core.config import settings
from core.database import get_setting, set_setting
from core.redis_client import redis_db
from data_ingestion.daily_node import DailyDataNode
from data_ingestion.greeks_engine import GreeksEngine
from data_ingestion.live_market_poller import LiveMarketPoller
from data_ingestion.macro_node import MacroDataNode
from data_ingestion.orderflow_engine import OrderflowEngine
from data_ingestion.primary_node import PrimaryDataNode
from strategy_engine.brain import StrategyBrain


class ModeUpdate(BaseModel):
    mode: str


class PaperFundsUpdate(BaseModel):
    funds: float


class ClosePositionRequest(BaseModel):
    symbol: Optional[str] = None


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("API")

# Global backend engine instances
daily_node = DailyDataNode()
orderflow_engine = OrderflowEngine()
greeks_engine = GreeksEngine()
live_poller = LiveMarketPoller(greeks_engine=greeks_engine)
primary_node = PrimaryDataNode()
macro_node = MacroDataNode()
ai_brain = StrategyBrain(mode=settings.TRADING_MODE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("BOOTING AI SCALPING ENGINE & REAL-TIME FASTAPI SERVER")
    logger.info("=" * 60)

    try:
        await asyncio.wait_for(redis_db.connect(), timeout=2.0)
        logger.info("✓ Docker Redis In-Memory Store: ONLINE")
    except Exception as e:
        logger.warning(f"⚠️ Docker Redis unavailable ({e}). Using In-Memory Store Failover.")

    # Boot ALL live ingestion, computation, and AI nodes unconditionally
    # (redis_db seamlessly handles Docker Redis when online OR memory shim when offline)
    logger.info("Starting Real-Time Data Nodes (NSE + Groww + Yahoo + Upstox + Orderflow + Greeks)...")
    bg_tasks = [
        asyncio.create_task(daily_node.run()),
        asyncio.create_task(live_poller.run()),
        asyncio.create_task(macro_node.run()),
        asyncio.create_task(orderflow_engine.run()),
        asyncio.create_task(greeks_engine.run()),
        asyncio.create_task(primary_node.run()),
    ]

    # Wait briefly for initial real live quotes so the first WebSocket frame has real market numbers
    await asyncio.sleep(2.5)

    logger.info("Starting Strategy Engine (AI Brain)...")
    bg_tasks.append(asyncio.create_task(ai_brain.start()))

    yield

    logger.info("Shutting down AI Trading Engine...")
    try:
        await daily_node.stop()
        await live_poller.stop()
        await macro_node.stop()
        await primary_node.stop()
        ai_brain.is_running = False
        orderflow_engine.is_running = False
        greeks_engine.is_running = False
        for t in bg_tasks:
            t.cancel()
        await redis_db.close()
    except Exception:
        pass


app = FastAPI(lifespan=lifespan, title="AI Trading Engine API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Streams authentic live market data across all 32 dimensions, portfolio state,
    and AI decision contracts to the frontend Dashboard every 1 second.
    """
    await websocket.accept()
    logger.info("Dashboard WebSocket client connected.")

    try:
        while True:
            full_state = {}
            positions = {}
            exec_state = {}
            last_signal = {}
            decision_latest = {}

            try:
                full_state_raw = await asyncio.wait_for(redis_db.redis.get("FULL_MARKET_STATE"), timeout=0.8)
                if full_state_raw:
                    full_state = json.loads(full_state_raw)

                active_mode = getattr(ai_brain.risk_manager, "mode", settings.TRADING_MODE)
                pos_key = f"{active_mode}_POSITIONS"
                positions = await asyncio.wait_for(redis_db.get_json(pos_key), timeout=0.5) or {}
                exec_state = await asyncio.wait_for(redis_db.get_json("EXECUTION:STATE:LATEST"), timeout=0.5) or {}
                last_signal = await asyncio.wait_for(redis_db.get_json("LATEST_AI_SIGNAL"), timeout=0.5) or {}
                decision_latest = await asyncio.wait_for(redis_db.get_json("DECISION:LATEST"), timeout=0.5) or last_signal
            except Exception:
                pass

            raw_funds = get_setting("PAPER_FUNDS", str(getattr(settings, "MAX_CAPITAL", 50000)))
            try:
                paper_funds_val = round(float(raw_funds), 2)
            except Exception:
                paper_funds_val = float(getattr(settings, "MAX_CAPITAL", 50000))

            # Build real live state directly from StateBuilder if Brain loop hasn't published yet
            if not full_state or not full_state.get("indices", {}).get("NIFTY50", {}).get("ltp"):
                full_state = await ai_brain.state_builder.build_market_state_dict()
                if full_state and full_state.get("indices", {}).get("NIFTY50", {}).get("ltp"):
                    await redis_db.set_json("FULL_MARKET_STATE", full_state)

            if not decision_latest:
                n_ltp = full_state.get("indices", {}).get("NIFTY50", {}).get("ltp", 0.0)
                v_ltp = full_state.get("indices", {}).get("INDIAVIX", {}).get("ltp", 0.0)
                is_open = full_state.get("is_market_open", False)
                min_conf = getattr(ai_brain.llm_client, "min_confidence", 78)
                decision_latest = {
                    "decision_id": "DEC_LIVE_MONITORING",
                    "action": "OBSERVE" if is_open else "MARKET_CLOSED",
                    "direction": "NEUTRAL",
                    "setup": "PATIENCE_PROTOCOL",
                    "symbol": "NIFTY",
                    "lots": 0,
                    "confidence": 0,
                    "reason": (
                        f"Live telemetry synchronized (NIFTY: ₹{n_ltp:,.2f}, India VIX: {v_ltp:.2f}). "
                        + (f"Awaiting >= {min_conf}% multi-factor alignment before entry." if is_open else "Market closed — monitoring live global cues, GIFT Nifty, and pre-market anchors.")
                    ),
                }
                last_signal = decision_latest

            payload = {
                "market_state": full_state,
                "positions": positions,
                "last_signal": last_signal,
                "last_decision": decision_latest,
                "status": "ONLINE" if full_state.get("indices", {}).get("NIFTY50", {}).get("ltp") else "WARMING_UP",
                "trading_mode": getattr(ai_brain.risk_manager, "mode", "PAPER"),
                "paper_funds": paper_funds_val,
                "execution_state": exec_state,
            }

            await websocket.send_json(payload)
            await asyncio.sleep(1)

    except WebSocketDisconnect:
        logger.info("Dashboard WebSocket disconnected.")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")


@app.get("/api/candles/{symbol}")
async def get_market_candles(symbol: str = "NIFTY50", interval: str = "1m", range: str = "1D"):
    """Returns real exchange intraday (1m..1h) or long-term historical (1d/1wk across 1M..MAX) OHLC candles."""
    sym_upper = symbol.upper()
    if "BANK" in sym_upper:
        norm_sym = "BANKNIFTY"
    elif "VIX" in sym_upper:
        norm_sym = "INDIAVIX"
    elif "IT" in sym_upper:
        norm_sym = "NIFTYIT"
    else:
        norm_sym = "NIFTY50"

    iv_clean = interval.strip()
    range_clean = range.strip().upper()

    if norm_sym in ("NIFTY50", "BANKNIFTY") and iv_clean.lower() == "1m" and range_clean == "1D":
        cached = await redis_db.get_json(f"CHART:CANDLES:{norm_sym}")
        if cached and cached.get("candles"):
            return {
                "symbol": norm_sym,
                "interval": "1m",
                "range": "1D",
                "candles": cached["candles"],
                "source": "live_cache",
            }

    candles = await asyncio.to_thread(live_poller._fetch_real_candles_sync, norm_sym, iv_clean, range_clean)
    return {
        "symbol": norm_sym,
        "interval": iv_clean,
        "range": range_clean,
        "candles": candles,
        "source": "exchange_direct",
    }


@app.post("/api/kill_switch")
async def trigger_kill_switch():
    """Emergency route to square off all positions and halt the system."""
    logger.critical("KILL SWITCH TRIGGERED VIA API!")
    await ai_brain.risk_manager._trigger_kill_switch()
    ai_brain.is_running = False
    await redis_db.set_json(
        "DECISION:LATEST",
        {
            "decision_id": "EMERGENCY_HALT",
            "action": "CLOSE_ALL",
            "direction": "NEUTRAL",
            "setup": "KILL_SWITCH",
            "symbol": "",
            "lots": 0,
            "confidence": 100,
            "reason": "Emergency Kill Switch activated via API — all open positions liquidated and risk engine halted.",
        },
    )
    return {"status": "success", "message": "Kill switch activated. All positions closed."}


@app.post("/api/system/reset_halt")
async def reset_halt_state():
    """Resumes RiskManager after an intentional emergency halt in PAPER mode."""
    ai_brain.risk_manager.is_halted = False
    if not ai_brain.is_running:
        ai_brain.is_running = True
        asyncio.create_task(ai_brain.start())
    await ai_brain.risk_manager.sync_execution_state()
    return {"status": "success", "message": "System halt cleared and execution state synchronized."}


@app.post("/api/close_position")
async def close_single_position(payload: ClosePositionRequest):
    """Squares off an open position cleanly without triggering permanent kill-switch halt."""
    rm = ai_brain.risk_manager
    target_sym = (payload.symbol or "").strip()
    if rm.mode == "PAPER":
        positions = await redis_db.get_json("PAPER_POSITIONS") or {}
        closed_any = False
        for sym, pos in list(positions.items()):
            qty = int(pos.get("net_qty", 0) or 0)
            if qty == 0 or (target_sym and sym != target_sym):
                continue
            await rm.process_decision({
                "action": "SELL" if qty > 0 else "BUY",
                "symbol": sym,
                "qty": abs(qty),
                "confidence": 100,
                "reason": "Manual Square-Off via Dashboard",
            })
            closed_any = True
        return {
            "status": "success" if closed_any else "noop",
            "message": f"Squared off open position{' for ' + target_sym if target_sym else ''}." if closed_any else "Position already flat.",
        }

    if rm.groww_router:
        await rm.groww_router.close_all_positions()
    await rm.sync_execution_state()
    return {"status": "success", "message": "Live square-off request dispatched."}


@app.post("/api/set_mode")
async def set_trading_mode(payload: ModeUpdate):
    """Toggles between PAPER and LIVE trading mode with router authentication & strict conviction lock."""
    target_mode = payload.mode.upper()
    if target_mode not in ["PAPER", "LIVE"]:
        return {"status": "error", "message": "Invalid mode."}

    if target_mode == "LIVE":
        has_groww = bool(getattr(settings, "GROWW_API_KEY", ""))
        has_shoonya = bool(getattr(settings, "SHOONYA_USER_ID", "") and getattr(settings, "SHOONYA_API_SECRET", ""))
        if not (has_groww or has_shoonya):
            return {"status": "error", "message": "MISSING_CREDENTIALS"}
        try:
            from execution_engine.fallback_router import DhanFallbackRouter
            from execution_engine.groww_router import GrowwRouter

            router = GrowwRouter()
            if not await router.login():
                return {"status": "error", "message": "LIVE_BROKER_AUTH_FAILED"}
            ai_brain.risk_manager.groww_router = router
            ai_brain.risk_manager.dhan_router = DhanFallbackRouter()
        except Exception as e:
            logger.error(f"Failed to init live routers: {e}")
            return {"status": "error", "message": f"LIVE_INIT_ERROR: {e}"}

    ai_brain.risk_manager.mode = target_mode
    ai_brain.llm_client.min_confidence = (
        90 if target_mode == "LIVE" else max(70, int(getattr(settings, "LLM_MIN_CONFIDENCE", 78) or 78))
    )
    await ai_brain.risk_manager.sync_execution_state()
    logger.warning(f"TRADING MODE SWITCHED TO: {target_mode} (min_conf={ai_brain.llm_client.min_confidence}%)")
    return {"status": "success", "message": f"Trading mode set to {target_mode}"}


@app.get("/api/paper_funds")
async def get_paper_funds():
    funds = get_setting("PAPER_FUNDS", "50000.0")
    return {"funds": float(funds)}


@app.post("/api/paper_funds")
async def update_paper_funds(payload: PaperFundsUpdate):
    if payload.funds <= 0 or payload.funds > 100_000_000:
        return {"status": "error", "message": "Funds must be a positive finite amount up to ₹10 Cr."}
    set_setting("PAPER_FUNDS", str(round(float(payload.funds), 2)))
    await ai_brain.risk_manager.sync_execution_state()
    logger.info(f"Paper trading funds updated to {payload.funds}")
    return {"status": "success", "funds": payload.funds}


def _safe_hold_seconds(entry_ts: Optional[str], exit_ts: Optional[str]) -> Optional[int]:
    if not entry_ts or not exit_ts:
        return None
    try:
        return max(0, int((datetime.fromisoformat(exit_ts) - datetime.fromisoformat(entry_ts)).total_seconds()))
    except Exception:
        return None


def _pair_round_trip_trades(chronological_trades: list[dict], live_ltp_map: dict[str, Optional[float]]) -> list[dict]:
    """Pairs sequential BUY/SELL rows into round-trip trade summaries with entry, exit, fees, and current live LTP."""
    open_lots: dict[tuple[str, str], list[dict]] = {}
    paired: list[dict] = []

    for row in chronological_trades:
        mode = str(row.get("mode") or "PAPER").upper()
        sym = str(row.get("symbol") or "")
        act = str(row.get("action") or "").upper()
        key = (mode, sym)
        live_ltp = live_ltp_map.get(sym)

        if act == "BUY":
            open_lots.setdefault(key, []).append(row)
        elif act == "SELL":
            queue = open_lots.get(key) or []
            entry = queue.pop(0) if queue else None
            entry_px = float(entry["price"]) if entry and entry.get("price") is not None else None
            exit_px = float(row.get("price") or 0.0)
            qty = int(row.get("qty") or (entry.get("qty") if entry else 0) or 0)
            recorded_pnl = float(row.get("pnl") or 0.0)
            gross_pnl = (
                round(recorded_pnl, 2)
                if recorded_pnl != 0.0 or entry_px is None
                else round((exit_px - entry_px) * qty, 2)
            )
            brokerage = 120.0 if (mode == "PAPER" and entry is not None) else (60.0 if mode == "PAPER" else 0.0)
            net_pnl = round(gross_pnl - brokerage, 2)
            if_held_pnl = (
                round((live_ltp - entry_px) * qty, 2)
                if (live_ltp is not None and entry_px is not None)
                else None
            )
            paired.append({
                "id": f"{entry.get('id') if entry else 'X'}-{row.get('id')}",
                "status": "CLOSED",
                "side": "LONG",
                "mode": mode,
                "symbol": sym,
                "qty": qty,
                "entry_time": entry.get("timestamp") if entry else None,
                "entry_price": entry_px,
                "exit_time": row.get("timestamp"),
                "exit_price": exit_px,
                "hold_seconds": _safe_hold_seconds(entry.get("timestamp") if entry else None, row.get("timestamp")),
                "current_ltp": live_ltp,
                "gross_pnl": gross_pnl,
                "brokerage": brokerage,
                "net_pnl": net_pnl,
                "if_held_pnl": if_held_pnl,
                "fund_after": float(row.get("fund_balance") or 0.0),
                "confidence": int((entry or row).get("confidence") or 0),
                "entry_reason": entry.get("reason") if entry else None,
                "exit_reason": row.get("reason"),
            })

    # Any unmatched BUY still open
    for (_, sym), entries in open_lots.items():
        live_ltp = live_ltp_map.get(sym)
        for entry in entries:
            entry_px = float(entry.get("price") or 0.0)
            qty = int(entry.get("qty") or 0)
            unrealized = round(((live_ltp if live_ltp is not None else entry_px) - entry_px) * qty, 2)
            paired.append({
                "id": f"OPEN-{entry.get('id')}",
                "status": "OPEN",
                "side": "LONG",
                "mode": str(entry.get("mode") or "PAPER").upper(),
                "symbol": sym,
                "qty": qty,
                "entry_time": entry.get("timestamp"),
                "entry_price": entry_px,
                "exit_time": None,
                "exit_price": None,
                "hold_seconds": None,
                "current_ltp": live_ltp,
                "gross_pnl": unrealized,
                "brokerage": 60.0 if str(entry.get("mode") or "").upper() == "PAPER" else 0.0,
                "net_pnl": unrealized,
                "if_held_pnl": unrealized,
                "fund_after": float(entry.get("fund_balance") or 0.0),
                "confidence": int(entry.get("confidence") or 0),
                "entry_reason": entry.get("reason"),
                "exit_reason": None,
            })

    paired.reverse()
    return paired


@app.get("/api/trades")
async def get_trades(mode: str = "ALL", start_date: str = None, end_date: str = None):
    db_path = os.path.join(os.path.dirname(__file__), "trading_records.db")
    if not os.path.exists(db_path):
        return {"trades": [], "round_trips": []}

    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        query = "SELECT * FROM trade_logs WHERE 1=1"
        params = []
        if mode != "ALL":
            query += " AND mode = ?"
            params.append(mode.upper())
        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date)

        query += " ORDER BY id DESC LIMIT 500"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        trades = [dict(row) for row in rows]
        conn.close()

        # Enrich with live option LTP from Redis
        live_ltp_map: dict[str, Optional[float]] = {}
        unique_syms = {str(t.get("symbol") or "") for t in trades if t.get("symbol")}
        for sym in unique_syms:
            try:
                tick = await ai_brain.risk_manager.paper_trader.get_live_quote(sym)
                ltp_val = float(tick.get("ltp") or 0.0) if tick else 0.0
                live_ltp_map[sym] = round(ltp_val, 2) if ltp_val > 0 else None
            except Exception:
                live_ltp_map[sym] = None

        for t in trades:
            t["current_ltp"] = live_ltp_map.get(str(t.get("symbol") or ""))

        round_trips = _pair_round_trip_trades(list(reversed(trades)), live_ltp_map)
        return {"trades": trades, "round_trips": round_trips}
    except Exception as e:
        logger.error(f"Failed to fetch trades: {e}")
        return {"trades": [], "round_trips": [], "error": str(e)}


@app.get("/api/system/health")
async def get_system_health():
    """Diagnostics for subsystem health across DB, Docker Redis, Upstox, and NSE/Groww Poller."""
    health = {
        "database_connected": False,
        "redis_connected": redis_db.is_connected,
        "broker_configured": False,
        "data_receiving": False,
        "upstox_token_valid": False,
        "live_poller_active": False,
        "errors": [],
    }

    db_path = os.path.join(os.path.dirname(__file__), "trading_records.db")
    if os.path.exists(db_path):
        health["database_connected"] = True
    else:
        health["errors"].append("SQLite Database 'trading_records.db' not found.")

    try:
        if redis_db.is_connected:
            await redis_db.redis.ping()
        else:
            health["errors"].append("Docker Redis offline — operating on In-Memory Store Failover.")

        keys = await redis_db.redis.keys("LTP:*")
        if keys:
            health["data_receiving"] = True
        else:
            health["errors"].append("No live market ticks cached yet.")

        up_status = await redis_db.get_json("SYSTEM:UPSTOX_STATUS")
        if up_status and up_status.get("token_valid"):
            health["upstox_token_valid"] = True
        else:
            health["errors"].append("Upstox access token expired/missing (401) — using NSE + Groww + Yahoo live feeds.")

        feed_status = await redis_db.get_json("SYSTEM:FEED_STATUS")
        if feed_status and feed_status.get("nifty_ltp"):
            health["live_poller_active"] = True

        llm_status = await redis_db.get_json("SYSTEM:LLM_STATUS")
        health["llm_status"] = llm_status or {
            "healthy": False,
            "configured_cloud_count": 0,
            "active_providers": [],
            "action_required": "LLM status initializing...",
        }
        if llm_status and llm_status.get("action_required"):
            health["errors"].append(llm_status["action_required"])
    except Exception as e:
        health["errors"].append(f"Health probe exception: {e}")

    has_groww = bool(getattr(settings, "GROWW_API_KEY", ""))
    has_shoonya = bool(getattr(settings, "SHOONYA_USER_ID", "") and getattr(settings, "SHOONYA_API_SECRET", ""))
    if has_groww or has_shoonya:
        health["broker_configured"] = True
    else:
        health["errors"].append("No Live Broker execution credentials found.")

    health["active_mode"] = getattr(ai_brain.risk_manager, "mode", settings.TRADING_MODE)
    health["is_halted"] = getattr(ai_brain.risk_manager, "is_halted", False)
    health["daily_trades_count"] = getattr(ai_brain.risk_manager, "daily_trades_count", 0)
    health["daily_pnl"] = getattr(ai_brain.risk_manager, "daily_pnl", 0.0)
    return health


@app.get("/api/system/logs")
async def get_system_logs():
    log_path = os.path.join(os.path.dirname(__file__), "logs", "trading_engine.log")
    if not os.path.exists(log_path):
        return {"logs": ["Log file not initialized yet."]}

    try:
        with open(log_path, "r") as f:
            lines = f.readlines()
            return {"logs": lines[-100:]}
    except Exception as e:
        return {"logs": [f"Failed to read logs: {e}"]}


@app.post("/api/eod_snapshot")
async def trigger_eod_snapshot():
    try:
        from data_ingestion.eod_summarizer import EODSummarizer
        summarizer = EODSummarizer()
        result = await summarizer.generate_and_save_eod_snapshot()
        return {"status": "success", "result": result}
    except Exception as e:
        logger.error(f"Failed to trigger EOD snapshot: {e}")
        return {"status": "error", "message": str(e)}


@app.get("/api/quant_rag")
async def get_quant_rag_status():
    try:
        from strategy_engine.episodic_memory import QuantEpisodicMemoryRAG
        rag = QuantEpisodicMemoryRAG()
        full_state_raw = await redis_db.redis.get("FULL_MARKET_STATE")
        state_dict = json.loads(full_state_raw) if full_state_raw else {}
        precedents = rag.search_similar_regimes(state_dict)
        return {"status": "success", "precedents": precedents}
    except Exception as e:
        logger.error(f"Failed to fetch Quant RAG: {e}")
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)

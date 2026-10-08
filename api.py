import asyncio
import json
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from core.redis_client import redis_db
from core.config import settings
from data_ingestion.primary_node import PrimaryDataNode
from data_ingestion.orderflow_engine import OrderflowEngine
from data_ingestion.greeks_engine import GreeksEngine
from data_ingestion.macro_node import MacroDataNode
from strategy_engine.brain import StrategyBrain
import uvicorn
from pydantic import BaseModel

class ModeUpdate(BaseModel):
    mode: str

logger = logging.getLogger("API")

# Global instances of the backend engines
primary_node = PrimaryDataNode()
orderflow_engine = OrderflowEngine()
greeks_engine = GreeksEngine()
macro_node = MacroDataNode()
ai_brain = StrategyBrain(mode=settings.TRADING_MODE)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start all trading engine background tasks
    logger.info("=" * 60)
    logger.info("BOOTING AI SCALPING ENGINE & FASTAPI SERVER")
    logger.info("=" * 60)
    
    # 0. Connect to Redis
    await redis_db.connect()
    
    # 1. Boot up Fast Loop (Data & Aggregation)
    logger.info("Starting Data Nodes & Microsecond Engines...")
    asyncio.create_task(primary_node.run())
    asyncio.create_task(orderflow_engine.run())
    asyncio.create_task(greeks_engine.run())
    asyncio.create_task(macro_node.run())
    
    # Allow 2 seconds for websockets to connect and Redis state to build
    await asyncio.sleep(2)
    
    # 2. Boot up Slow Loop (AI Strategy Engine)
    logger.info("Starting Strategy Engine (Dual-Brain)...")
    asyncio.create_task(ai_brain.start())
    
    yield # Server is running
    
    # Shutdown: Stop all tasks
    logger.info("Shutting down AI Trading Engine...")
    await primary_node.stop()
    await macro_node.stop()
    ai_brain.is_running = False
    await redis_db.close()

app = FastAPI(lifespan=lifespan, title="AI Trading Engine API")

# Allow CORS for Next.js Dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict to frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Streams the live market state and active positions from Redis to the frontend Dashboard.
    """
    await websocket.accept()
    logger.info("New Dashboard WebSocket connection established.")
    
    try:
        while True:
            # Fetch complete dense market state from Strategy Brain
            full_state_raw = await redis_db.redis.get("FULL_MARKET_STATE")
            full_state = json.loads(full_state_raw) if full_state_raw else {}
            
            # Fetch latest positions
            pos_key = f"{settings.TRADING_MODE}_POSITIONS"
            positions = await redis_db.get_json(pos_key) or {}
            
            # Fetch latest AI Reason / Signal
            last_signal = await redis_db.get_json("LATEST_AI_SIGNAL") or {}
            
            # Send mega payload to frontend
            payload = {
                "market_state": full_state,
                "positions": positions,
                "last_signal": last_signal,
                "status": "ONLINE" if ai_brain.is_running else "OFFLINE",
                "trading_mode": ai_brain.risk_manager.mode
            }
            
            await websocket.send_json(payload)
            await asyncio.sleep(1) # Stream updates every 1 second
            
    except WebSocketDisconnect:
        logger.info("Dashboard WebSocket disconnected.")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")

@app.post("/api/kill_switch")
async def trigger_kill_switch():
    """Emergency route to square off all positions and halt the system."""
    logger.critical("KILL SWITCH TRIGGERED VIA API!")
    await ai_brain.risk_manager._trigger_kill_switch()
    ai_brain.is_running = False
    return {"status": "success", "message": "Kill switch activated. All positions closed."}

@app.post("/api/set_mode")
async def set_trading_mode(payload: ModeUpdate):
    """Toggles between PAPER and LIVE trading mode."""
    target_mode = payload.mode.upper()
    if target_mode not in ["PAPER", "LIVE"]:
        return {"status": "error", "message": "Invalid mode."}
        
    if target_mode == "LIVE":
        # Check if they have execution credentials
        if not getattr(settings, "GROWW_API_KEY", "") and not getattr(settings, "DHAN_ACCESS_TOKEN", ""):
            return {"status": "error", "message": "MISSING_CREDENTIALS"}
        
        # Initialize execution routers safely
        try:
            from execution_engine.groww_router import GrowwRouter
            from execution_engine.fallback_router import DhanFallbackRouter
            ai_brain.risk_manager.groww_router = GrowwRouter()
            ai_brain.risk_manager.dhan_router = DhanFallbackRouter()
        except Exception as e:
            logger.error(f"Failed to init routers: {e}")
            
    ai_brain.risk_manager.mode = target_mode
    logger.warning(f"TRADING MODE SWITCHED TO: {target_mode}")
    return {"status": "success", "message": f"Trading mode set to {target_mode}"}

import sqlite3
import os

@app.get("/api/trades")
async def get_trades(mode: str = "ALL", start_date: str = None, end_date: str = None):
    """Fetch trade logs for analytics dashboard."""
    db_path = os.path.join(os.path.dirname(__file__), "trading_records.db")
    if not os.path.exists(db_path):
        return {"trades": []}
        
    try:
        conn = sqlite3.connect(db_path)
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
            
        query += " ORDER BY timestamp DESC LIMIT 500"
        cursor.execute(query, params)
        rows = cursor.fetchall()
        trades = [dict(row) for row in rows]
        conn.close()
        return {"trades": trades}
    except Exception as e:
        logger.error(f"Failed to fetch trades: {e}")
        return {"trades": [], "error": str(e)}

@app.get("/api/system/health")
async def get_system_health():
    """Run diagnostics for the analytics dashboard."""
    health = {
        "database_connected": False,
        "redis_connected": False,
        "broker_configured": False,
        "data_receiving": False,
        "errors": []
    }
    
    # 1. Check DB
    db_path = os.path.join(os.path.dirname(__file__), "trading_records.db")
    if os.path.exists(db_path):
        health["database_connected"] = True
    else:
        health["errors"].append("SQLite Database 'trading_records.db' not found.")
        
    # 2. Check Redis & Data
    try:
        ping = await redis_db.redis.ping()
        health["redis_connected"] = ping
        # Check if we have recent ticks
        keys = await redis_db.redis.keys("LTP:*")
        if keys:
            health["data_receiving"] = True
        else:
            health["errors"].append("Redis connected but no market data (LTP) found. Is Upstox streaming?")
    except Exception as e:
        health["errors"].append(f"Redis connection failed: {e}")
        
    # 3. Check Broker
    has_groww = bool(getattr(settings, "GROWW_API_KEY", ""))
    has_dhan = bool(getattr(settings, "DHAN_ACCESS_TOKEN", ""))
    if has_groww or has_dhan:
        health["broker_configured"] = True
    else:
        health["errors"].append("No Live Broker (Groww/Dhan) API keys found in config.")
        
    return health

@app.get("/api/system/logs")
async def get_system_logs():
    """Fetch recent system logs."""
    log_path = os.path.join(os.path.dirname(__file__), "gini_trading.log")
    if not os.path.exists(log_path):
        return {"logs": ["Log file not found."]}
        
    try:
        # Read last 100 lines
        with open(log_path, 'r') as f:
            lines = f.readlines()
            return {"logs": lines[-100:]}
    except Exception as e:
        return {"logs": [f"Failed to read logs: {e}"]}

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)

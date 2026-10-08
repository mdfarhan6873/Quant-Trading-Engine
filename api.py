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

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)

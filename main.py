import asyncio
import logging
from data_ingestion.primary_node import PrimaryDataNode
from data_ingestion.orderflow_engine import OrderflowEngine
from data_ingestion.greeks_engine import GreeksEngine
from data_ingestion.macro_node import MacroDataNode
from strategy_engine.brain import StrategyBrain
from core.config import settings

# Configure Global Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("SystemBoot")

async def main():
    logger.info("=" * 60)
    logger.info("BOOTING AI SCALPING ENGINE (DUAL-BRAIN CONSENSUS)")
    logger.info("=" * 60)
    
    # 1. Initialize Components
    primary_node = PrimaryDataNode()
    orderflow_engine = OrderflowEngine()
    greeks_engine = GreeksEngine()
    macro_node = MacroDataNode()
    ai_brain = StrategyBrain(mode=settings.TRADING_MODE)
    
    # 2. Boot up Fast Loop (Data & Aggregation)
    logger.info("Starting Data Nodes & Microsecond Engines...")
    fast_loop_tasks = [
        asyncio.create_task(primary_node.run()),
        asyncio.create_task(orderflow_engine.run()),
        asyncio.create_task(greeks_engine.run()),
        asyncio.create_task(macro_node.run())
    ]
    
    # Allow 2 seconds for websockets to connect and Redis state to build
    await asyncio.sleep(2)
    
    # 3. Boot up Slow Loop (AI Strategy Engine)
    logger.info("Starting Strategy Engine (Dual-Brain)...")
    strategy_task = asyncio.create_task(ai_brain.start())
    
    # 4. Keep the system running
    try:
        await asyncio.gather(*fast_loop_tasks, strategy_task)
    except KeyboardInterrupt:
        logger.warning("Keyboard Interrupt received. Shutting down...")
        await primary_node.stop()
    except Exception as e:
        logger.critical(f"System crashed: {e}")
        await primary_node.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

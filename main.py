import asyncio
import logging
from core.config import settings
from core.redis_client import redis_db
from data_ingestion.daily_node import DailyDataNode
from data_ingestion.greeks_engine import GreeksEngine
from data_ingestion.live_market_poller import LiveMarketPoller
from data_ingestion.macro_node import MacroDataNode
from data_ingestion.orderflow_engine import OrderflowEngine
from data_ingestion.primary_node import PrimaryDataNode
from strategy_engine.brain import StrategyBrain

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("SystemBoot")


async def main():
    logger.info("=" * 60)
    logger.info("BOOTING AI SCALPING ENGINE (DUAL-BRAIN CONSENSUS)")
    logger.info("=" * 60)

    try:
        await asyncio.wait_for(redis_db.connect(), timeout=2.0)
    except Exception as e:
        logger.warning(f"Docker Redis unavailable ({e}), running with In-Memory Store Failover.")

    daily_node = DailyDataNode()
    orderflow_engine = OrderflowEngine()
    greeks_engine = GreeksEngine()
    live_poller = LiveMarketPoller(greeks_engine=greeks_engine)
    primary_node = PrimaryDataNode()
    macro_node = MacroDataNode()
    ai_brain = StrategyBrain(mode=settings.TRADING_MODE)

    logger.info("Starting Data Nodes & Real-Time Engines...")
    fast_loop_tasks = [
        asyncio.create_task(daily_node.run()),
        asyncio.create_task(live_poller.run()),
        asyncio.create_task(primary_node.run()),
        asyncio.create_task(orderflow_engine.run()),
        asyncio.create_task(greeks_engine.run()),
        asyncio.create_task(macro_node.run()),
    ]

    await asyncio.sleep(2.5)

    logger.info("Starting Strategy Engine (Dual-Brain)...")
    strategy_task = asyncio.create_task(ai_brain.start())

    try:
        await asyncio.gather(*fast_loop_tasks, strategy_task)
    except KeyboardInterrupt:
        logger.warning("Keyboard Interrupt received. Shutting down...")
        await daily_node.stop()
        await live_poller.stop()
        await primary_node.stop()
        await macro_node.stop()
    except Exception as e:
        logger.critical(f"System crashed: {e}")
        await primary_node.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

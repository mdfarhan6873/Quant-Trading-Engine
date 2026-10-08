import asyncio
import logging
import time
from core.config import settings
from strategy_engine.state_builder import StateBuilder
from strategy_engine.llm_client import LLMClient
from strategy_engine.risk_manager import RiskManager

logger = logging.getLogger(__name__)

class StrategyBrain:
    """
    The core Slow Loop of the trading system.
    Runs every 1-5 seconds.
    Compresses Redis state -> Queries LLM -> Validates Risk -> Executes Trade.
    """
    def __init__(self, mode: str = "PAPER"):
        self.mode = mode
        self.polling_interval = 2.0 # 2 seconds
        self.is_running = False
        
        self.state_builder = StateBuilder()
        self.llm_client = LLMClient()
        self.risk_manager = RiskManager(mode=self.mode)

    async def start(self):
        """Initializes the Brain and begins the trading loop."""
        logger.info(f"INITIALIZING AI BRAIN IN [{self.mode}] MODE USING [DUAL-BRAIN CONSENSUS]")
        
        if not await self.risk_manager.initialize():
            logger.critical("Failed to arm Risk Manager. System cannot start.")
            return

        self.is_running = True
        logger.info(f"AI Brain Online. Polling every {self.polling_interval} seconds.")
        
        # Start the Fast Loop in the background for Trailing SL & Theta Protection
        asyncio.create_task(self.risk_manager.monitor_open_positions())
        
        system_prompt = await self.state_builder.get_system_prompt()
        
        while self.is_running:
            try:
                start_time = time.time()
                
                # 1. State Compression (Eyes)
                market_state = await self.state_builder.build_market_state()
                from core.redis_client import redis_db
                await redis_db.redis.set("FULL_MARKET_STATE", market_state)
                
                
                # 2. Query LLM (Brain)
                decision = await self.llm_client.get_decision(system_prompt, market_state)
                
                if decision:
                    from core.redis_client import redis_db
                    await redis_db.set_json("LATEST_AI_SIGNAL", decision)
                    logger.info(f"LLM DECISION: {decision}")
                    # 3. Risk Gauntlet & Execution (Shield & Hands)
                    await self.risk_manager.process_decision(decision)
                else:
                    logger.warning("LLM returned no valid decision this cycle.")
                    
                # 4. Latency tracking
                latency = time.time() - start_time
                logger.debug(f"Slow Loop Cycle Time: {latency:.2f}s")
                
                # Dynamic sleep to maintain exact polling interval
                sleep_time = max(0.1, self.polling_interval - latency)
                await asyncio.sleep(sleep_time)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Strategy Brain Exception: {e}")
                await asyncio.sleep(self.polling_interval)

    async def stop(self):
        self.is_running = False
        await self.risk_manager.shutdown()
        await self.llm_client.shutdown()
        logger.info("AI Brain Offline.")

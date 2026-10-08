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
        self.polling_interval = 15.0 # 15 seconds (respect Gemini free tier limits)
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
        
        import json
        
        while self.is_running:
            try:
                start_time = time.time()
                
                # 1. State Compression (Eyes)
                market_state = await self.state_builder.build_market_state()
                from core.redis_client import redis_db
                await redis_db.redis.set("FULL_MARKET_STATE", market_state)
                
                # Check if market is open
                state_dict = json.loads(market_state)
                is_open = state_dict.get("is_market_open", True)
                
                # Adjust polling interval
                if not is_open:
                    self.polling_interval = 3600.0  # Poll every 1 hour when closed to save API quotas
                else:
                    self.polling_interval = 15.0  # Normal active polling
                
                # Fetch dynamic system prompt based on market state
                system_prompt = await self.state_builder.get_system_prompt(is_open=is_open)
                # Adaptive State Hashing (Architecture 10/10: Save API Rate Limits)
                import hashlib
                state_hash = hashlib.md5(market_state.encode()).hexdigest()
                
                # Only query the LLM if market state has meaningfully changed, OR if 60 seconds have passed.
                # We skip the check if we have open positions (need constant monitoring)
                has_open_positions = '"portfolio":{}' not in market_state.replace(" ", "")
                
                if not getattr(self, 'last_state_hash', None):
                    self.last_state_hash = ""
                    self.last_llm_call = 0
                
                time_since_last_call = time.time() - self.last_llm_call
                
                if state_hash == self.last_state_hash and time_since_last_call < 60.0 and not has_open_positions:
                    logger.debug("State identical to previous cycle. Skipping LLM query to preserve rate limits (10/10 Architecture).")
                    decision = None
                else:
                    # 2. Query LLM (Brain)
                    self.last_state_hash = state_hash
                    self.last_llm_call = time.time()
                    decision = await self.llm_client.get_decision(system_prompt, market_state)
                
                if decision:
                    await redis_db.set_json("LATEST_AI_SIGNAL", decision)
                    logger.info(f"LLM DECISION: {decision}")
                    
                    if is_open:
                        # 3. Risk Gauntlet & Execution (Shield & Hands)
                        await self.risk_manager.process_decision(decision)
                    else:
                        logger.info("Market Closed. Displaying Post-Market Analysis on Dashboard.")
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

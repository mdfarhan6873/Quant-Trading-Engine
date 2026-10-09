import asyncio
import logging
import time
import datetime
import pytz
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
                analysis_window = state_dict.get("analysis_window", None)
                
                self.polling_interval = 5.0
                
                # Fetch dynamic system prompt based on market state
                system_prompt = await self.state_builder.get_system_prompt(is_open=is_open, analysis_window=analysis_window)
                
                # Adaptive State Hashing (Architecture 10/10: Save API Rate Limits)
                import hashlib
                state_hash = hashlib.md5(market_state.encode()).hexdigest()
                has_open_positions = '"portfolio":{}' not in market_state.replace(" ", "")
                
                if not getattr(self, 'last_state_hash', None):
                    self.last_state_hash = ""
                    self.last_llm_call = 0
                
                time_since_last_call = time.time() - self.last_llm_call
                
                decision = None
                is_analysis_call = False
                
                if analysis_window:
                    # Check if we already ran analysis for this window today
                    today_str = datetime.datetime.now(pytz.timezone('Asia/Kolkata')).date().isoformat()
                    ran_key = f"ANALYSIS_RAN:{analysis_window}:{today_str}"
                    already_ran = await redis_db.redis.get(ran_key)
                    
                    if not already_ran:
                        logger.info(f"Triggering Scheduled Market Analysis: {analysis_window}")
                        self.last_llm_call = time.time()
                        decision = await self.llm_client.get_decision(system_prompt, market_state)
                        if decision:
                            await redis_db.redis.set(ran_key, "1", ex=86400) # expire in 24h
                            # Save to a rolling list so the UI or live market state can read the last 3 events
                            history_raw = await redis_db.redis.get("LATEST_MARKET_ANALYSIS")
                            history = json.loads(history_raw) if history_raw else []
                            if not isinstance(history, list):
                                history = [history]
                            
                            history.append({
                                "window": analysis_window, 
                                "time": datetime.datetime.now(pytz.timezone('Asia/Kolkata')).isoformat(),
                                "analysis": decision
                            })
                            # Keep only the last 3 analyses (e.g., Yesterday Post-Market, Today 8:30, Today 9:14)
                            history = history[-3:]
                            await redis_db.redis.set("LATEST_MARKET_ANALYSIS", json.dumps(history))
                        is_analysis_call = True
                    else:
                        logger.debug(f"Analysis for {analysis_window} already completed today.")
                        decision = None
                elif not is_open:
                    logger.debug("Market is closed. Updating state but skipping LLM query to save API quotas.")
                    decision = None
                elif state_hash == self.last_state_hash and time_since_last_call < 60.0 and not has_open_positions:
                    logger.debug("State identical to previous cycle. Skipping LLM query to preserve rate limits (10/10 Architecture).")
                    decision = None
                else:
                    # 2. Query LLM (Brain) Live
                    self.last_state_hash = state_hash
                    self.last_llm_call = time.time()
                    decision = await self.llm_client.get_decision(system_prompt, market_state)
                
                if decision:
                    if is_analysis_call:
                        logger.info(f"ANALYSIS REPORT GENERATED: {decision.get('reason')}")
                    else:
                        await redis_db.set_json("LATEST_AI_SIGNAL", decision)
                        logger.info(f"LLM DECISION: {decision}")
                        
                        if is_open:
                            # 3. Risk Gauntlet & Execution (Shield & Hands)
                            await self.risk_manager.process_decision(decision)
                else:
                    if is_open:
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

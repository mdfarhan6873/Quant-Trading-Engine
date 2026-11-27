import asyncio
import logging
import time
import datetime
import pytz
from core.config import settings
from strategy_engine.state_builder import StateBuilder
from strategy_engine.llm_client import LLMClient
from strategy_engine.risk_manager import RiskManager
from core.redis_client import redis_db

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

        await self.llm_client.publish_status()
        self.is_running = True
        logger.info(f"AI Brain Online. Polling every {self.polling_interval} seconds.")

        # Start the Fast Loop in the background for Trailing SL & Theta Protection
        asyncio.create_task(self.risk_manager.monitor_open_positions())

        import json
        import hashlib

        while self.is_running:
            try:
                start_time = time.time()

                # 1. State Compression (Eyes)
                state_dict = await self.state_builder.build_market_state_dict()
                market_state = json.dumps(state_dict, separators=(",", ":")) if state_dict else "{}"
                await redis_db.redis.set("FULL_MARKET_STATE", market_state)

                is_open = state_dict.get("is_market_open", True)
                analysis_window = state_dict.get("analysis_window", None)
                self.polling_interval = 5.0

                system_prompt = await self.state_builder.get_system_prompt(
                    is_open=is_open, analysis_window=analysis_window
                )

                state_hash = hashlib.md5(market_state.encode()).hexdigest()
                has_open_positions = bool(state_dict.get("portfolio"))

                if not getattr(self, "last_state_hash", None):
                    self.last_state_hash = ""
                    self.last_llm_call = 0.0

                time_since_last_call = time.time() - self.last_llm_call
                decision = None
                is_analysis_call = False
                should_call_llm = False

                prev_decision = await redis_db.get_json("DECISION:LATEST")
                exec_state = await redis_db.get_json("EXECUTION:STATE:LATEST")
                tripartite_payload = (
                    self.state_builder.build_tripartite_llm_payload(
                        state_dict,
                        previous_decision=prev_decision,
                        execution_state=exec_state,
                    )
                    if state_dict
                    else "{}"
                )

                tz = pytz.timezone("Asia/Kolkata")
                today_str = datetime.datetime.now(tz).date().isoformat()

                if analysis_window:
                    ran_key = f"ANALYSIS_RAN:{analysis_window}:{today_str}"
                    already_ran = await redis_db.redis.get(ran_key)
                    if not already_ran:
                        logger.info(f"Triggering Scheduled Market Analysis: {analysis_window}")
                        self.last_llm_call = time.time()
                        should_call_llm = True
                        decision = await self.llm_client.get_decision(system_prompt, tripartite_payload)
                        if decision:
                            await redis_db.redis.set(ran_key, "1", ex=86400)
                            history_raw = await redis_db.redis.get("LATEST_MARKET_ANALYSIS")
                            history = json.loads(history_raw) if history_raw else []
                            if not isinstance(history, list):
                                history = [history]
                            history.append({
                                "window": analysis_window,
                                "time": datetime.datetime.now(tz).isoformat(),
                                "analysis": decision,
                            })
                            history = history[-3:]
                            await redis_db.redis.set("LATEST_MARKET_ANALYSIS", json.dumps(history))
                        is_analysis_call = True
                elif not is_open:
                    # Trigger automatic once-daily EOD closing archival after 15:35 IST on weekdays
                    now_ist = datetime.datetime.now(tz)
                    if now_ist.weekday() < 5 and (now_ist.hour > 15 or (now_ist.hour == 15 and now_ist.minute >= 35)):
                        eod_key = f"EOD_RAN:{today_str}"
                        if not await redis_db.redis.get(eod_key) and state_dict:
                            try:
                                from data_ingestion.eod_summarizer import EODSummarizer

                                await EODSummarizer().generate_and_save_eod_snapshot()
                                await redis_db.redis.set(eod_key, "1", ex=86400)
                            except Exception as eod_err:
                                logger.debug(f"Auto EOD snapshot skipped: {eod_err}")

                    # Run once on startup/afterhours if no decision exists yet so dashboard reflects macro regime
                    existing_signal = await redis_db.get_json("LATEST_AI_SIGNAL")
                    if not existing_signal and state_dict and time_since_last_call >= 300.0:
                        self.last_llm_call = time.time()
                        should_call_llm = True
                        decision = await self.llm_client.get_decision(system_prompt, tripartite_payload)
                        is_analysis_call = True
                    else:
                        logger.debug("Market is closed. Updating state but skipping LLM query to save API quotas.")
                else:
                    if has_open_positions or time_since_last_call >= 60.0:
                        should_call_llm = True
                        self.last_state_hash = state_hash
                        self.last_llm_call = time.time()
                        decision = await self.llm_client.get_decision(system_prompt, tripartite_payload)
                    else:
                        logger.debug(f"Throttling LLM query to preserve rate limits (Next call in {60.0 - time_since_last_call:.1f}s)")

                if decision:
                    if is_open and not is_analysis_call:
                        # Run Risk Gauntlet BEFORE finalizing persistence so risk_controls reflect final approval
                        await self.risk_manager.process_decision(decision)

                    await redis_db.set_json("LATEST_AI_SIGNAL", decision)
                    await redis_db.set_json("DECISION:LATEST", decision)
                    dec_id = decision.get("decision_id") or f"DEC_{today_str}_{int(time.time())}"
                    await redis_db.set_json(f"DECISION:HISTORY:{dec_id}", decision, ex=86400)

                    timeline_key = f"DECISION:TIMELINE:{today_str}"
                    timeline = await redis_db.get_json(timeline_key) or []
                    if not isinstance(timeline, list):
                        timeline = []
                    timeline.append({
                        "decision_id": dec_id,
                        "timestamp": decision.get("timestamp"),
                        "action": decision.get("action"),
                        "symbol": decision.get("symbol"),
                        "confidence": decision.get("confidence"),
                        "provider": decision.get("provider"),
                    })
                    await redis_db.set_json(timeline_key, timeline[-120:], ex=86400)

                    if is_analysis_call:
                        logger.info(f"ANALYSIS REPORT GENERATED: {decision.get('reason')}")
                    else:
                        logger.info(f"LLM DECISION [{decision.get('provider')}]: {decision.get('action')} {decision.get('symbol')} ({decision.get('confidence')}%)")
                elif should_call_llm:
                    logger.warning("LLM returned no valid decision this cycle (check SYSTEM:LLM_STATUS).")
                    
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

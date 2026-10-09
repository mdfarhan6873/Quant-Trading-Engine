import json
import logging
import httpx
import asyncio
from typing import Dict, Any, Optional
from core.config import settings

logger = logging.getLogger(__name__)

class LLMClient:
    """
    Interfaces with the chosen LLM (Gemini 1.5 Pro / Anthropic Claude 3.5 Sonnet).
    Handles API requests, strictly enforces JSON output, and parses the trading decision.
    """
    def __init__(self):
        self.gemini_key = settings.GEMINI_API_KEY
        self.anthropic_key = settings.ANTHROPIC_API_KEY
        
        # We use httpx for async, low-latency REST calls without bulky SDK overhead
        self.client = httpx.AsyncClient(timeout=30.0) # Increased timeout to 30s to give Gemini enough time to think

    async def get_decision(self, system_prompt: str, market_state_json: str) -> Optional[Dict[str, Any]]:
        """
        Sends the compressed market state to BOTH LLMs simultaneously (Dual-Brain Consensus).
        Returns a valid trade ONLY if average confidence >= 90% and actions align.
        """
        # Call both concurrently for ultra-low latency
        results = await asyncio.gather(
            self._call_anthropic(system_prompt, market_state_json),
            self._call_gemini(system_prompt, market_state_json),
            return_exceptions=True
        )
        
        anthropic_decision = results[0] if not isinstance(results[0], Exception) else None
        gemini_decision = results[1] if not isinstance(results[1], Exception) else None
        
        valid_decisions = [d for d in (anthropic_decision, gemini_decision) if d is not None]
        
        if not valid_decisions:
            logger.error("Both LLM Providers failed.")
            return None
            
        if len(valid_decisions) == 1:
            # Fallback mode: one failed, rely on the other but strict 90% check
            decision = valid_decisions[0]
            if decision.get("confidence", 0) >= 90:
                logger.warning(f"Single-Brain Execution (Confidence {decision['confidence']}%): {decision['action']}")
                return decision
            else:
                logger.info(f"Single-Brain HOLD (Confidence < 90%): {decision.get('confidence')}%")
                return {"action": "HOLD", "symbol": "", "qty": 0}
                
        # Both succeeded: Check for consensus
        a_action, g_action = anthropic_decision.get("action"), gemini_decision.get("action")
        a_sym, g_sym = anthropic_decision.get("symbol"), gemini_decision.get("symbol")
        
        # If either says CLOSE_ALL, prioritize safety
        if a_action == "CLOSE_ALL" or g_action == "CLOSE_ALL":
            return {"action": "CLOSE_ALL", "symbol": "", "qty": 0, "reason": "Emergency Liquidation consensus."}
            
        if a_action == g_action and a_sym == g_sym and a_action != "HOLD":
            avg_confidence = (anthropic_decision.get("confidence", 0) + gemini_decision.get("confidence", 0)) / 2.0
            if avg_confidence >= 90:
                logger.info(f"DUAL-BRAIN CONSENSUS APPROVED: {a_action} {a_sym} | Avg Conf: {avg_confidence}%")
                return {
                    "action": a_action,
                    "symbol": a_sym,
                    "qty": anthropic_decision.get("qty", 0), # Default to Anthropic qty sizing
                    "confidence": avg_confidence,
                    "reason": f"Anthropic: {anthropic_decision.get('reason')} | Gemini: {gemini_decision.get('reason')}"
                }
            else:
                logger.info(f"DUAL-BRAIN REJECTED (Confidence {avg_confidence}% < 90%)")
                return {"action": "HOLD", "symbol": "", "qty": 0}
                
        # Conflict / Disagreement
        logger.info(f"DUAL-BRAIN DISAGREEMENT: Anthropic({a_action}) vs Gemini({g_action}). Defaulting to HOLD.")
        return {"action": "HOLD", "symbol": "", "qty": 0}

    async def _call_gemini(self, system_prompt: str, market_state_json: str) -> Optional[Dict[str, Any]]:
        """Calls Google Gemini API (gemini-1.5-flash for max speed)."""
        if not self.gemini_key:
            logger.error("GEMINI_API_KEY is missing.")
            return None
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={self.gemini_key}"
        
        payload = {
            "system_instruction": {
                "parts": {"text": system_prompt}
            },
            "contents": [{
                "parts": [{"text": f"Current Market State:\n{market_state_json}"}]
            }],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.0 # ZERO hallucination, strictly deterministic logical processing
            }
        }
        
        try:
            response = await self.client.post(url, json=payload)
            if response.status_code == 200:
                data = response.json()
                text_response = data["candidates"][0]["content"]["parts"][0]["text"]
                return self._parse_json(text_response)
            else:
                logger.error(f"Gemini API Error: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Gemini Request Failed: {e}")
            return None

    async def _call_anthropic(self, system_prompt: str, market_state_json: str) -> Optional[Dict[str, Any]]:
        """Calls Anthropic Claude API (claude-3-haiku-20240307 for max speed)."""
        if not self.anthropic_key:
            logger.error("ANTHROPIC_API_KEY is missing.")
            return None
            
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.anthropic_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        payload = {
            "model": "claude-3-haiku-20240307",
            "max_tokens": 150,
            "temperature": 0.0,
            "system": system_prompt,
            "messages": [
                {"role": "user", "content": f"Current Market State:\n{market_state_json}"}
            ]
        }
        
        try:
            response = await self.client.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                data = response.json()
                text_response = data["content"][0]["text"]
                return self._parse_json(text_response)
            else:
                logger.error(f"Anthropic API Error: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            logger.error(f"Anthropic Request Failed: {e}")
            return None

    def _parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Safely parses JSON out of the LLM response."""
        try:
            # Strip markdown formatting if the model disobeys and wraps in ```json
            text = text.strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
                
            decision = json.loads(text.strip())
            
            # Validate schema
            if "action" in decision and "symbol" in decision and "qty" in decision and "confidence" in decision:
                return decision
            else:
                logger.error(f"LLM returned invalid schema: {decision}")
                return None
                
        except json.JSONDecodeError:
            logger.error(f"LLM did not return valid JSON. Raw output: {text}")
            return None

    async def shutdown(self):
        await self.client.aclose()

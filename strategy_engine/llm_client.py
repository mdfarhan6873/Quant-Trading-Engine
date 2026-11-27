import asyncio
import datetime
import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
import pytz

from core.config import settings
from core.redis_client import redis_db

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Multi-provider Quant Brain client supporting free & paid LLM providers:
    - Free Cloud APIs: Groq (gsk_...), Google Gemini (AIza...), OpenRouter (:free), Cerebras
    - Free Local LLM: Ollama (http://127.0.0.1:11434)
    - Paid Optional: Anthropic Claude
    Enforces Contract 1 JSON normalization, independent factor_audit summary_metrics recalculation,
    and deterministic execution safety locks.
    """

    def __init__(self):
        self.tokenrouter_key = (getattr(settings, "TOKENROUTER_API_KEY", "") or "").strip()
        self.tokenrouter_base_url = (
            getattr(settings, "TOKENROUTER_BASE_URL", "https://api.tokenrouter.com/v1") or "https://api.tokenrouter.com/v1"
        ).strip().rstrip("/")
        self.tokenrouter_model = (
            getattr(settings, "TOKENROUTER_MODEL", "deepseek/deepseek-v4.1-flash-1017-free")
            or "deepseek/deepseek-v4.1-flash-1017-free"
        ).strip()
        self.tokenrouter_fallback_model = (
            getattr(settings, "TOKENROUTER_FALLBACK_MODEL", "") or ""
        ).strip()
        self.gemini_key = (settings.GEMINI_API_KEY or "").strip()
        self.anthropic_key = (settings.ANTHROPIC_API_KEY or "").strip()
        self.groq_key = (getattr(settings, "GROQ_API_KEY", "") or "").strip()
        self.openrouter_key = (getattr(settings, "OPENROUTER_API_KEY", "") or "").strip()
        self.cerebras_key = (getattr(settings, "CEREBRAS_API_KEY", "") or "").strip()
        self.ollama_base_url = (getattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434") or "").strip().rstrip("/")
        self.ollama_model = (getattr(settings, "OLLAMA_MODEL", "llama3.1:8b") or "llama3.1:8b").strip()
        is_live = str(getattr(settings, "TRADING_MODE", "PAPER")).upper() == "LIVE"
        self.min_confidence = 90 if is_live else max(70, int(getattr(settings, "LLM_MIN_CONFIDENCE", 78) or 78))
        self._client: Optional[httpx.AsyncClient] = None
        self.provider_status: Dict[str, Dict[str, Any]] = self._init_provider_status()

    def _init_provider_status(self) -> Dict[str, Dict[str, Any]]:
        gemini_hint = None
        if self.gemini_key and not self.gemini_key.startswith("AIza"):
            gemini_hint = "Key does not start with 'AIza' (Google AI Studio API key required)."

        return {
            "tokenrouter": {
                "configured": bool(self.tokenrouter_key),
                "free_tier": True,
                "model": self.tokenrouter_model,
                "status": "READY" if self.tokenrouter_key else "NOT_CONFIGURED",
                "last_error": None,
                "latency_ms": None,
            },
            "groq": {
                "configured": bool(self.groq_key),
                "free_tier": True,
                "model": getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile"),
                "status": "READY" if self.groq_key else "NOT_CONFIGURED",
                "last_error": None,
                "latency_ms": None,
            },
            "gemini": {
                "configured": bool(self.gemini_key),
                "free_tier": True,
                "model": "gemini-2.5-flash",
                "status": "READY" if self.gemini_key else "NOT_CONFIGURED",
                "last_error": gemini_hint,
                "latency_ms": None,
            },
            "openrouter": {
                "configured": bool(self.openrouter_key),
                "free_tier": True,
                "model": getattr(settings, "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
                "status": "READY" if self.openrouter_key else "NOT_CONFIGURED",
                "last_error": None,
                "latency_ms": None,
            },
            "cerebras": {
                "configured": bool(self.cerebras_key),
                "free_tier": True,
                "model": getattr(settings, "CEREBRAS_MODEL", "llama-3.3-70b"),
                "status": "READY" if self.cerebras_key else "NOT_CONFIGURED",
                "last_error": None,
                "latency_ms": None,
            },
            "anthropic": {
                "configured": bool(self.anthropic_key),
                "free_tier": False,
                "model": "claude-3-5-sonnet-20241022",
                "status": "READY" if self.anthropic_key else "NOT_CONFIGURED",
                "last_error": None,
                "latency_ms": None,
            },
            "ollama": {
                "configured": bool(self.ollama_base_url),
                "free_tier": True,
                "model": self.ollama_model,
                "status": "STANDBY_LOCAL",
                "last_error": None,
                "latency_ms": None,
            },
        }

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
        return self._client

    def has_any_cloud_key(self) -> bool:
        return any(bool(k) for k in (self.tokenrouter_key, self.groq_key, self.gemini_key, self.openrouter_key, self.cerebras_key, self.anthropic_key))

    async def publish_status(self):
        """Persists LLM provider health & actionable setup guidance to SYSTEM:LLM_STATUS in Redis."""
        active_ok = [name for name, st in self.provider_status.items() if st.get("status") == "OK"]
        configured = [name for name, st in self.provider_status.items() if st.get("configured") and name != "ollama"]
        auth_issues = [
            f"{name}: {st.get('last_error')}"
            for name, st in self.provider_status.items()
            if name != "ollama" and st.get("configured") and st.get("status") == "AUTH_ERROR"
        ]
        transient_issues = [
            f"{name}: {st.get('last_error') or st.get('status')}"
            for name, st in self.provider_status.items()
            if name != "ollama" and st.get("configured") and st.get("last_error") and st.get("status") not in ("OK", "AUTH_ERROR", "NOT_CONFIGURED")
        ]

        action_required = None
        transient_warning = None
        if not configured and not active_ok:
            action_required = (
                "No cloud LLM API key configured. Add a FREE TOKENROUTER_API_KEY, GROQ_API_KEY, "
                "GEMINI_API_KEY (AIza...), OPENROUTER_API_KEY, or run local Ollama in .env."
            )
        elif auth_issues and not active_ok:
            action_required = (
                f"LLM key rejected ({'; '.join(auth_issues)}). "
                "Check .env LLM API key / quota settings (TokenRouter, Groq, or Google AI Studio)."
            )
        elif transient_issues and not active_ok:
            transient_warning = f"Retrying next cycle ({'; '.join(transient_issues)})."

        payload = {
            "healthy": len(active_ok) > 0,
            "configured_cloud_count": len(configured),
            "active_providers": active_ok,
            "action_required": action_required,
            "transient_warning": transient_warning,
            "providers": self.provider_status,
            "updated_at": time.time(),
        }
        await redis_db.set_json("SYSTEM:LLM_STATUS", payload)
        return payload

    async def get_decision(
        self,
        system_prompt: str,
        market_state_json: str,
        previous_decision_json: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Queries all configured cloud LLM providers concurrently (with local Ollama fallback).
        Enforces Contract 1 audit checks and deterministic multi-brain consensus.
        """
        # Support both pre-formatted Tripartite JSON and legacy callers passing state + previous_decision_json
        if '"part_b_current_market_state"' in market_state_json:
            user_content = market_state_json
        elif previous_decision_json:
            user_content = (
                "=== IMMUTABLE PREVIOUS DECISION RECORD ===\n"
                f"{previous_decision_json}\n"
                "==========================================\n\n"
                "=== LIVE MARKET STATE MATRIX ===\n"
                f"{market_state_json}"
            )
        else:
            user_content = market_state_json

        tasks: List[tuple[str, Any]] = []
        if self.tokenrouter_key:
            tasks.append(("tokenrouter", self._call_tokenrouter(system_prompt, user_content)))
        if self.groq_key:
            tasks.append((
                "groq",
                self._call_openai_compatible(
                    "groq",
                    "https://api.groq.com/openai/v1/chat/completions",
                    self.groq_key,
                    getattr(settings, "GROQ_MODEL", "llama-3.3-70b-versatile"),
                    system_prompt,
                    user_content,
                ),
            ))
        if self.gemini_key:
            tasks.append(("gemini", self._call_gemini(system_prompt, user_content)))
        if self.openrouter_key:
            tasks.append((
                "openrouter",
                self._call_openai_compatible(
                    "openrouter",
                    "https://openrouter.ai/api/v1/chat/completions",
                    self.openrouter_key,
                    getattr(settings, "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
                    system_prompt,
                    user_content,
                    extra_headers={"HTTP-Referer": "http://localhost:3000", "X-Title": "JINI Quant Terminal"},
                ),
            ))
        if self.cerebras_key:
            tasks.append((
                "cerebras",
                self._call_openai_compatible(
                    "cerebras",
                    "https://api.cerebras.ai/v1/chat/completions",
                    self.cerebras_key,
                    getattr(settings, "CEREBRAS_MODEL", "llama-3.3-70b"),
                    system_prompt,
                    user_content,
                ),
            ))
        if self.anthropic_key:
            tasks.append(("anthropic", self._call_anthropic(system_prompt, user_content)))

        valid_decisions: List[Dict[str, Any]] = []
        if tasks:
            results = await asyncio.gather(*(t[1] for t in tasks), return_exceptions=True)
            for (name, _), res in zip(tasks, results):
                if isinstance(res, dict):
                    res["provider"] = name
                    valid_decisions.append(res)

        # Fallback to local Ollama ONLY if no cloud provider returned a valid decision
        if not valid_decisions and self.ollama_base_url:
            ollama_res = await self._call_ollama(system_prompt, user_content)
            if isinstance(ollama_res, dict):
                ollama_res["provider"] = "ollama"
                valid_decisions.append(ollama_res)

        await self.publish_status()

        if not valid_decisions:
            logger.warning("No configured LLM provider returned a valid JSON decision.")
            return None

        if len(valid_decisions) == 1:
            return self._enforce_contract1(valid_decisions[0])

        # Multi-brain Consensus (2+ active providers)
        return self._merge_consensus(valid_decisions)

    def _merge_consensus(self, decisions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merges 2+ valid provider decisions with safety-first consensus while preserving Contract 1 audit."""
        primary = next((d for d in decisions if d.get("factor_audit")), decisions[0])
        actions = [str(d.get("action", "OBSERVE")).upper() for d in decisions]
        reasons = [f"[{d.get('provider', 'llm').upper()}] {d.get('reason', 'N/A')}" for d in decisions]

        if any(a == "CLOSE_ALL" for a in actions):
            merged = dict(primary)
            merged.update({
                "action": "CLOSE_ALL",
                "symbol": "",
                "lots": 0,
                "qty": 0,
                "confidence": 100,
                "reason": " | ".join(reasons),
                "provider": "+".join(d.get("provider", "llm") for d in decisions),
            })
            return self._enforce_contract1(merged)

        if all(a == "ANALYSIS" for a in actions) or any(a == "ANALYSIS" for a in actions):
            merged = dict(primary)
            merged.update({
                "action": "ANALYSIS",
                "symbol": primary.get("symbol", "MACRO"),
                "lots": 0,
                "qty": 0,
                "confidence": round(sum(float(d.get("confidence", 85)) for d in decisions) / len(decisions), 1),
                "reason": " | ".join(reasons),
                "provider": "+".join(d.get("provider", "llm") for d in decisions),
            })
            return self._enforce_contract1(merged)

        first_action = actions[0]
        first_sym = decisions[0].get("symbol", "")
        all_agree = all(a == first_action and d.get("symbol", "") == first_sym for a, d in zip(actions, decisions))
        avg_conf = round(sum(float(d.get("confidence", 0)) for d in decisions) / len(decisions), 1)

        merged = dict(primary)
        merged["provider"] = "+".join(d.get("provider", "llm") for d in decisions)
        merged["reason"] = " | ".join(reasons)

        if all_agree and first_action not in ("OBSERVE", "HOLD", "NO_TRADE"):
            merged["confidence"] = avg_conf
            return self._enforce_contract1(merged)

        if not all_agree:
            merged["action"] = "OBSERVE"
            merged["direction"] = "NEUTRAL"
            merged["symbol"] = ""
            merged["lots"] = 0
            merged["qty"] = 0
            merged["confidence"] = min(float(d.get("confidence", 60)) for d in decisions)
            merged["reason"] = f"MULTI-BRAIN DIVERGENCE ({'/'.join(actions)} -> OBSERVE): " + " | ".join(reasons)

        return self._enforce_contract1(merged)

    def _enforce_contract1(self, decision: Dict[str, Any]) -> Dict[str, Any]:
        """Recomputes factor_audit.summary_metrics independently in Python and enforces Patience/Audit locks."""
        tz = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.datetime.now(tz)

        decision.setdefault("decision_id", f"DEC_{now_ist.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:4].upper()}")
        decision.setdefault("timestamp", now_ist.isoformat())
        decision.setdefault("instrument", "NIFTY50")
        decision.setdefault("timeframe", "1m")
        decision.setdefault("direction", "NEUTRAL")
        decision.setdefault("setup", "REGIME_OBSERVATION")

        action = str(decision.get("action", "OBSERVE")).upper()
        confidence = float(decision.get("confidence", 0) or 0)
        lots = int(decision.get("lots", decision.get("qty", 0)) or 0)

        # Recalculate factor_audit summary_metrics deterministically if factor array exists
        audit = decision.get("factor_audit")
        hard_unavailable = 0
        critical_conflicts = 0
        if isinstance(audit, dict) and isinstance(audit.get("factors"), list) and audit["factors"]:
            factors = audit["factors"]
            available = sum(1 for f in factors if str(f.get("status", "")).upper() == "AVAILABLE")
            conflicting = sum(1 for f in factors if str(f.get("status", "")).upper() == "CONFLICTING")
            unavailable = sum(1 for f in factors if str(f.get("status", "")).upper() == "UNAVAILABLE")
            bullish = sum(1 for f in factors if str(f.get("evidence", "")).upper() == "BULLISH")
            bearish = sum(1 for f in factors if str(f.get("evidence", "")).upper() == "BEARISH")
            neutral = sum(1 for f in factors if str(f.get("evidence", "")).upper() in ("NEUTRAL", "MISSING"))
            hard_unavailable = sum(
                1 for f in factors
                if bool(f.get("critical")) and str(f.get("status", "")).upper() == "UNAVAILABLE"
            )
            critical_conflicts = sum(
                1 for f in factors
                if bool(f.get("critical")) and str(f.get("status", "")).upper() == "CONFLICTING"
            )
            # Only fail Contract 1 on broken/unavailable critical feeds or >2 major critical conflicts
            critical_failures = hard_unavailable + max(0, critical_conflicts - 2)
            audit["summary_metrics"] = {
                "total_factors_evaluated": len(factors),
                "available_count": available,
                "conflicting_count": conflicting,
                "unavailable_count": unavailable,
                "bullish_count": bullish,
                "bearish_count": bearish,
                "neutral_count": neutral,
                "critical_failures": critical_failures,
            }

        is_entry = action in ("ENTER_CALL", "ENTER_PUT", "BUY")
        execution_authorized = False
        if is_entry:
            if hard_unavailable > 0:
                decision["action"] = "OBSERVE"
                decision["direction"] = "NEUTRAL"
                decision["symbol"] = ""
                lots = 0
                decision["reason"] = f"[PYTHON AUDIT GUARDRAIL: {hard_unavailable} critical feed(s) unavailable] {decision.get('reason', '')}"
            elif critical_conflicts > 2:
                decision["action"] = "OBSERVE"
                decision["symbol"] = ""
                lots = 0
                decision["reason"] = f"[PYTHON AUDIT GUARDRAIL: {critical_conflicts} critical conflicts (>2 max)] {decision.get('reason', '')}"
            elif confidence < self.min_confidence:
                decision["action"] = "OBSERVE"
                decision["symbol"] = ""
                lots = 0
                decision["reason"] = (
                    f"[PATIENCE GUARDRAIL: Confidence {confidence:.0f}% < {self.min_confidence}%] "
                    f"{decision.get('reason', '')}"
                )
            else:
                execution_authorized = True
        elif action in ("EXIT", "REDUCE", "CLOSE_ALL", "SELL"):
            execution_authorized = True

        decision["lots"] = lots
        decision["qty"] = lots
        decision["risk_controls"] = {
            "execution_authorized": execution_authorized,
            "max_lots_permitted": lots if execution_authorized else 0,
            "min_confidence_required": self.min_confidence,
        }
        return decision

    async def _call_tokenrouter(self, system_prompt: str, user_content: str) -> Optional[Dict[str, Any]]:
        """Calls TokenRouter OpenAI-compatible free models with automatic fallback to secondary allowed model."""
        url = f"{self.tokenrouter_base_url}/chat/completions"
        models = [self.tokenrouter_model]
        if self.tokenrouter_fallback_model and self.tokenrouter_fallback_model not in models:
            models.append(self.tokenrouter_fallback_model)

        for model_name in models:
            self.provider_status["tokenrouter"]["model"] = model_name
            res = await self._call_openai_compatible(
                "tokenrouter",
                url,
                self.tokenrouter_key,
                model_name,
                system_prompt,
                user_content,
            )
            if isinstance(res, dict):
                return res
            if self.provider_status["tokenrouter"].get("status") == "AUTH_ERROR":
                return None
        return None

    async def _call_openai_compatible(
        self,
        provider_name: str,
        url: str,
        api_key: str,
        model: str,
        system_prompt: str,
        user_content: str,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Shared caller for OpenAI-compatible free/paid endpoints (TokenRouter, Groq, OpenRouter, Cerebras)."""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        base_payload: Dict[str, Any] = {
            "model": model,
            "temperature": 0.0,
            "max_tokens": 3500,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        }
        payload: Dict[str, Any] = {
            **base_payload,
            "response_format": {"type": "json_object"},
        }
        if provider_name == "tokenrouter":
            # Disable extended <think> chains on TokenRouter DeepSeek for 5-8s real-time latency instead of 80s+ timeouts
            payload["thinking"] = {"type": "disabled"}

        t0 = time.time()
        try:
            response = await self.client.post(url, headers=headers, json=payload)
            if response.status_code == 400:
                err_lower = response.text.lower()
                fallback_payload = dict(payload)
                changed = False
                if "thinking" in err_lower or "reasoning" in err_lower or "unknown" in err_lower or "unrecognized" in err_lower:
                    fallback_payload.pop("thinking", None)
                    changed = True
                if "response_format" in err_lower:
                    fallback_payload.pop("response_format", None)
                    changed = True
                if changed:
                    response = await self.client.post(url, headers=headers, json=fallback_payload)

            latency_ms = round((time.time() - t0) * 1000, 1)
            if response.status_code == 200:
                data = response.json()
                message = data["choices"][0]["message"]
                text_response = message.get("content") or message.get("reasoning_content") or ""
                parsed = self._parse_json(text_response)
                self.provider_status[provider_name].update({
                    "model": model,
                    "status": "OK" if parsed else "PARSE_ERROR",
                    "last_error": None if parsed else "Invalid JSON payload from model",
                    "latency_ms": latency_ms,
                })
                return parsed
            elif response.status_code in (401, 403):
                err_txt = response.text[:260]
                self.provider_status[provider_name].update({
                    "status": "AUTH_ERROR",
                    "last_error": f"HTTP {response.status_code}: {err_txt}",
                    "latency_ms": latency_ms,
                })
                logger.error(f"{provider_name.upper()} Auth Error ({response.status_code}): {err_txt}")
                return None
            elif response.status_code == 429:
                self.provider_status[provider_name].update({
                    "status": "RATE_LIMITED",
                    "last_error": "HTTP 429 rate/token limit reached",
                    "latency_ms": latency_ms,
                })
                logger.warning(f"{provider_name.upper()} rate limited (429).")
                return None
            else:
                err_txt = response.text[:260]
                self.provider_status[provider_name].update({
                    "status": "ERROR",
                    "last_error": f"HTTP {response.status_code}: {err_txt}",
                    "latency_ms": latency_ms,
                })
                logger.error(f"{provider_name.upper()} Error ({response.status_code}): {err_txt}")
                return None
        except Exception as e:
            err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            self.provider_status[provider_name].update({
                "status": "UNAVAILABLE",
                "last_error": err_msg[:260],
            })
            logger.error(f"{provider_name.upper()} Request Failed: {err_msg}")
            return None

    async def _call_gemini(self, system_prompt: str, user_content: str) -> Optional[Dict[str, Any]]:
        """Calls Google Gemini API with automatic dynamic model fallback."""
        if not self.gemini_key:
            return None

        models_to_try = [
            "gemini-2.5-flash",
            "gemini-2.0-flash",
            "gemini-2.5-flash-lite",
        ]

        payload = {
            "system_instruction": {"parts": {"text": system_prompt}},
            "contents": [{"parts": [{"text": user_content}]}],
            "generationConfig": {
                "response_mime_type": "application/json",
                "temperature": 0.0,
                "maxOutputTokens": 2500,
            },
        }

        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.gemini_key}"
            t0 = time.time()
            try:
                response = await self.client.post(url, json=payload)
                latency_ms = round((time.time() - t0) * 1000, 1)
                if response.status_code == 200:
                    data = response.json()
                    text_response = data["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = self._parse_json(text_response)
                    self.provider_status["gemini"].update({
                        "model": model,
                        "status": "OK" if parsed else "PARSE_ERROR",
                        "last_error": None if parsed else "Invalid JSON payload",
                        "latency_ms": latency_ms,
                    })
                    return parsed
                elif response.status_code in (400, 401, 403):
                    err_txt = response.text[:180]
                    is_auth = "API key not valid" in err_txt or response.status_code in (401, 403)
                    self.provider_status["gemini"].update({
                        "status": "AUTH_ERROR" if is_auth else "ERROR",
                        "last_error": f"HTTP {response.status_code}: {err_txt}",
                        "latency_ms": latency_ms,
                    })
                    logger.error(f"Gemini API Error ({model}): {response.status_code} - {err_txt}")
                    if is_auth:
                        return None
                elif response.status_code in (429, 500, 502, 503, 404):
                    self.provider_status["gemini"].update({
                        "status": "RATE_LIMITED" if response.status_code == 429 else "ERROR",
                        "last_error": f"HTTP {response.status_code} on {model}",
                        "latency_ms": latency_ms,
                    })
                    logger.warning(f"Gemini {model} unavailable ({response.status_code}). Trying next...")
                    continue
            except Exception as e:
                self.provider_status["gemini"].update({
                    "status": "UNAVAILABLE",
                    "last_error": str(e)[:180],
                })
                logger.error(f"Gemini Request Failed ({model}): {e}")
                continue

        return None

    async def _call_anthropic(self, system_prompt: str, user_content: str) -> Optional[Dict[str, Any]]:
        """Calls Anthropic Claude API."""
        if not self.anthropic_key:
            return None

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.anthropic_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        models = ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"]
        for model in models:
            payload = {
                "model": model,
                "max_tokens": 2500,
                "temperature": 0.0,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_content}],
            }
            t0 = time.time()
            try:
                response = await self.client.post(url, headers=headers, json=payload)
                latency_ms = round((time.time() - t0) * 1000, 1)
                if response.status_code == 200:
                    data = response.json()
                    text_response = data["content"][0]["text"]
                    parsed = self._parse_json(text_response)
                    self.provider_status["anthropic"].update({
                        "model": model,
                        "status": "OK" if parsed else "PARSE_ERROR",
                        "last_error": None if parsed else "Invalid JSON payload",
                        "latency_ms": latency_ms,
                    })
                    return parsed
                elif response.status_code in (429, 500, 502, 503):
                    continue
                else:
                    self.provider_status["anthropic"].update({
                        "status": "AUTH_ERROR" if response.status_code in (401, 403) else "ERROR",
                        "last_error": f"HTTP {response.status_code}: {response.text[:160]}",
                        "latency_ms": latency_ms,
                    })
                    return None
            except Exception as e:
                self.provider_status["anthropic"].update({"status": "UNAVAILABLE", "last_error": str(e)[:160]})
                continue
        return None

    async def _call_ollama(self, system_prompt: str, user_content: str) -> Optional[Dict[str, Any]]:
        """Queries a local Ollama daemon if installed and running locally (100% free, zero API keys)."""
        try:
            tags_resp = await self.client.get(f"{self.ollama_base_url}/api/tags", timeout=1.5)
            if tags_resp.status_code != 200:
                self.provider_status["ollama"]["status"] = "NOT_RUNNING"
                return None
            models = [m.get("name") for m in tags_resp.json().get("models", []) if m.get("name")]
            if not models:
                self.provider_status["ollama"].update({"status": "NO_MODELS", "last_error": "Ollama running but no models pulled."})
                return None
            chosen_model = self.ollama_model if self.ollama_model in models else models[0]
            self.provider_status["ollama"]["model"] = chosen_model

            t0 = time.time()
            chat_resp = await self.client.post(
                f"{self.ollama_base_url}/api/chat",
                json={
                    "model": chosen_model,
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": 0.0},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                },
                timeout=35.0,
            )
            latency_ms = round((time.time() - t0) * 1000, 1)
            if chat_resp.status_code == 200:
                text_response = chat_resp.json().get("message", {}).get("content", "")
                parsed = self._parse_json(text_response)
                self.provider_status["ollama"].update({
                    "configured": True,
                    "status": "OK" if parsed else "PARSE_ERROR",
                    "last_error": None if parsed else "Invalid JSON payload",
                    "latency_ms": latency_ms,
                })
                return parsed
        except Exception:
            self.provider_status["ollama"].update({"status": "NOT_RUNNING", "last_error": None})
        return None

    def _parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Safely parses and normalizes Contract 1 JSON out of an LLM response (stripping reasoning/think blocks)."""
        try:
            # Strip <think>...</think> blocks emitted by reasoning models
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()
            if text.startswith("```json"):
                text = text[7:]
            if text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]

            # Extract outermost JSON object if wrapped in stray commentary
            first_brace = text.find("{")
            last_brace = text.rfind("}")
            if first_brace != -1 and last_brace > first_brace:
                text = text[first_brace : last_brace + 1]

            decision = json.loads(text.strip())

            # Handle Contract 1 nested schema: { "decision": { "action": ... }, "factor_audit": ... }
            if "decision" in decision and isinstance(decision["decision"], dict):
                inner = decision["decision"]
                for k in ("action", "symbol", "confidence", "reason", "lots", "direction", "setup"):
                    if k not in decision and k in inner:
                        decision[k] = inner[k]

            if "lots" in decision and "qty" not in decision:
                decision["qty"] = decision["lots"]
            elif "qty" in decision and "lots" not in decision:
                decision["lots"] = decision["qty"]
            else:
                decision.setdefault("lots", 0)
                decision.setdefault("qty", 0)

            decision.setdefault("symbol", "")
            decision.setdefault("confidence", 75)

            valid_actions = {
                "OBSERVE", "ENTER_CALL", "ENTER_PUT", "HOLD",
                "EXIT", "NO_TRADE", "REDUCE", "CLOSE_ALL", "ANALYSIS",
            }
            act = str(decision.get("action", "")).upper()
            decision["action"] = act if act in valid_actions else "OBSERVE"
            return decision
        except json.JSONDecodeError:
            logger.error(f"LLM did not return valid JSON. Raw output: {text[:300]}")
            return None

    async def shutdown(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

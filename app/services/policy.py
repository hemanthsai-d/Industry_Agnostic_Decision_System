from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.models.schemas import DecisionType, PolicyResult, RiskLevel

logger = logging.getLogger(__name__)


class PolicyService:
    HIGH_RISK_TERMS = {"breach", "lawsuit", "fraud", "security incident", "legal threat"}

    def __init__(self, settings: Settings):
        self._settings = settings

    async def evaluate(
        self,
        issue_text: str,
        risk_level: RiskLevel,
        final_confidence: float,
        escalation_prob: float,
    ) -> PolicyResult:
        if self._settings.use_opa:
            opa_result = await self._evaluate_opa(issue_text, final_confidence, escalation_prob)
            if opa_result is not None:
                return opa_result

        return self._evaluate_local(issue_text, risk_level, final_confidence, escalation_prob)

    async def _evaluate_opa(
        self,
        issue_text: str,
        final_confidence: float,
        escalation_prob: float,
    ) -> PolicyResult | None:
        payload: dict[str, Any] = {
            "input": {
                "issue_text": issue_text,
                "final_confidence": final_confidence,
                "threshold": self._settings.base_confidence_threshold,
                "escalation_prob": escalation_prob,
                "max_auto_escalation": self._settings.max_auto_escalation_prob,
            }
        }
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.post(self._settings.opa_url, json=payload)
                resp.raise_for_status()
                data = resp.json().get("result", {})
                if not data:
                    return None
                return PolicyResult(
                    allow_auto_response=bool(data.get("allow_auto_response", False)),
                    final_decision=DecisionType(data.get("final_decision", "abstain")),
                    reason_codes=data.get("reason_codes", []),
                )
        except Exception:
            logger.exception('OPA evaluation failed, falling back to local policy.')
            return None

    def _evaluate_local(
        self,
        issue_text: str,
        risk_level: RiskLevel,
        final_confidence: float,
        escalation_prob: float,
    ) -> PolicyResult:
        txt = issue_text.lower()
        risk_hit = any(term in txt for term in self.HIGH_RISK_TERMS)
        threshold = self._settings.base_confidence_threshold + (0.05 if risk_level == RiskLevel.high else 0.0)

        if risk_hit:
            return PolicyResult(
                allow_auto_response=False,
                final_decision=DecisionType.escalate,
                reason_codes=["policy_high_risk"],
            )
        if final_confidence < threshold:
            return PolicyResult(
                allow_auto_response=False,
                final_decision=DecisionType.abstain,
                reason_codes=["low_confidence"],
            )
        if escalation_prob >= self._settings.max_auto_escalation_prob:
            return PolicyResult(
                allow_auto_response=False,
                final_decision=DecisionType.abstain,
                reason_codes=["high_escalation_risk"],
            )

        return PolicyResult(
            allow_auto_response=True,
            final_decision=DecisionType.recommend,
            reason_codes=[],
        )

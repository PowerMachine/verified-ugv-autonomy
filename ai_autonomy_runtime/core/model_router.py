from __future__ import annotations

from dataclasses import dataclass

from ai_autonomy_runtime.schemas.common import RiskLevel
from ai_autonomy_runtime.schemas.runtime_event import RuntimeEvent


@dataclass(frozen=True)
class ModelRoute:
    backend_name: str
    reason: str
    max_output_tokens: int
    requires_network: bool = False


class ModelRouter:
    def __init__(self, prefer_backend: str = "mock_model") -> None:
        self.prefer_backend = prefer_backend

    def route(
        self,
        event: RuntimeEvent,
        risk_level: str | RiskLevel = RiskLevel.LOW,
        remaining_budget_ms: float | None = None,
    ) -> ModelRoute:
        risk_value = risk_level.value if isinstance(risk_level, RiskLevel) else str(risk_level)
        if not event.requires_model_call:
            return ModelRoute("rule_fallback", "event_does_not_require_model", 0, False)
        if remaining_budget_ms is not None and remaining_budget_ms < 100.0:
            return ModelRoute("rule_fallback", "tight_slo_budget", 0, False)
        if risk_value in {RiskLevel.HIGH.value, RiskLevel.CRITICAL.value}:
            return ModelRoute("rule_fallback", "high_risk_prefers_deterministic_fallback", 0, False)
        return ModelRoute(self.prefer_backend, "model_call_allowed_by_budget_and_risk", 256, self.prefer_backend != "mock_model")

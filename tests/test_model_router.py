from __future__ import annotations

from ai_autonomy_runtime.core.model_router import ModelRouter
from ai_autonomy_runtime.schemas.runtime_event import RuntimeEvent, RuntimeEventType


def test_model_router_uses_rule_fallback_under_tight_budget() -> None:
    event = RuntimeEvent(event_type=RuntimeEventType.USER_GOAL, source="test", requires_model_call=True)
    route = ModelRouter().route(event, remaining_budget_ms=50)
    assert route.backend_name == "rule_fallback"


def test_model_router_uses_mock_when_budget_allows() -> None:
    event = RuntimeEvent(event_type=RuntimeEventType.USER_GOAL, source="test", requires_model_call=True)
    route = ModelRouter().route(event, remaining_budget_ms=500)
    assert route.backend_name == "mock_model"

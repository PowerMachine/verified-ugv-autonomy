from __future__ import annotations

from ai_autonomy_runtime.core.model_router import ModelRouter
from ai_autonomy_runtime.schemas.runtime_event import RuntimeEvent, RuntimeEventType


def run_router_benchmark() -> list[dict[str, object]]:
    router = ModelRouter()
    rows: list[dict[str, object]] = []
    event = RuntimeEvent(event_type=RuntimeEventType.USER_GOAL, source="benchmark", requires_model_call=True)
    for budget in [50, 200, 1000]:
        route = router.route(event, remaining_budget_ms=budget)
        rows.append({"budget_ms": budget, **route.__dict__})
    return rows

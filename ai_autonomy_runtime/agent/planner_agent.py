from __future__ import annotations

from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate, ActionType
from ai_autonomy_runtime.schemas.common import RiskLevel


class PlannerAgent:
    """Deterministic planner used until a model backend is configured."""

    def plan(self, goal: str, source_model: str = "rule_fallback") -> ActionCandidate:
        goal_lower = goal.lower()
        if "stop" in goal_lower:
            return ActionCandidate(
                action_type=ActionType.STOP,
                parameters={"reason": goal, "sequence_id": 0},
                ttl_ms=500,
                expected_duration_ms=100,
                risk_level=RiskLevel.LOW,
                requires_physical_execution=False,
                source_model=source_model,
            )
        if "inspect" in goal_lower or "area" in goal_lower:
            return ActionCandidate(
                action_type=ActionType.REPORT_ONLY,
                parameters={
                    "report": "Propose read-only inspection first; no robot motion requested.",
                    "goal": goal,
                    "sequence_id": 0,
                },
                ttl_ms=1000,
                expected_duration_ms=100,
                risk_level=RiskLevel.LOW,
                requires_physical_execution=False,
                source_model=source_model,
            )
        return ActionCandidate(
            action_type=ActionType.WAIT,
            parameters={"duration_ms": 250, "reason": "default conservative action", "sequence_id": 0},
            ttl_ms=1000,
            expected_duration_ms=250,
            risk_level=RiskLevel.LOW,
            requires_physical_execution=False,
            source_model=source_model,
        )

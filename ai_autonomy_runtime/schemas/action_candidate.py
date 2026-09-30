from __future__ import annotations

import time
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_autonomy_runtime.schemas.common import RiskLevel, make_id, utc_now


class ActionType(str, Enum):
    STOP = "stop"
    WAIT = "wait"
    FORWARD = "forward"
    BACKWARD = "backward"
    TURN_LEFT = "turn_left"
    TURN_RIGHT = "turn_right"
    VELOCITY_CANDIDATE = "velocity_candidate"
    PRIMITIVE_SEQUENCE = "primitive_sequence"
    SKILL_GRAPH = "skill_graph"
    INSPECT_POINT = "inspect_point"
    RETURN_HOME = "return_home"
    REPORT_ONLY = "report_only"


class ActionCandidate(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    candidate_id: str = Field(default_factory=lambda: make_id("candidate"))
    created_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000), ge=0)
    source: str = "manual"
    candidate_type: str = "ugv_motion"
    action_type: ActionType
    parameters: dict[str, Any] = Field(default_factory=dict)
    ttl_ms: int = Field(default=500, gt=0)
    created_at: datetime = Field(default_factory=utc_now)
    expected_duration_ms: int = Field(default=0, ge=0)
    risk_level: RiskLevel = RiskLevel.LOW
    requires_physical_execution: bool = False
    source_model: str = "rule_fallback"
    reason: str = ""

    def is_expired(self, now: datetime | None = None) -> bool:
        now = now or utc_now()
        return now > self.created_at + timedelta(milliseconds=self.ttl_ms)

    def is_safe_early_action(self) -> bool:
        return str(self.action_type) in {
            ActionType.STOP.value,
            ActionType.WAIT.value,
            ActionType.FORWARD.value,
            ActionType.BACKWARD.value,
            ActionType.TURN_LEFT.value,
            ActionType.TURN_RIGHT.value,
            ActionType.INSPECT_POINT.value,
            ActionType.RETURN_HOME.value,
            ActionType.REPORT_ONLY.value,
            ActionType.PRIMITIVE_SEQUENCE.value,
        }

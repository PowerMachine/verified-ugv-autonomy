from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_autonomy_runtime.schemas.common import Severity, make_id, utc_now


class RuntimeEventType(str, Enum):
    USER_GOAL = "user_goal"
    SENSOR_UPDATE = "sensor_update"
    PATH_BLOCKED = "path_blocked"
    TASK_STALLED = "task_stalled"
    LOCALIZATION_UNCERTAIN = "localization_uncertain"
    CAMERA_OBSERVATION = "camera_observation"
    LIDAR_OBSERVATION = "lidar_observation"
    MODEL_TIMEOUT = "model_timeout"
    JSON_PARSE_FAILURE = "json_parse_failure"
    SLO_VIOLATION = "slo_violation"
    UNSAFE_CANDIDATE = "unsafe_candidate"
    PROMOTION_SUCCESS = "promotion_success"
    ROLLBACK_TRIGGERED = "rollback_triggered"


class RuntimeEvent(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    event_id: str = Field(default_factory=lambda: make_id("event"))
    event_type: RuntimeEventType
    source: str
    timestamp: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)
    severity: Severity = Severity.INFO
    slo_budget_ms: int | None = None
    requires_model_call: bool = False

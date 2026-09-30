from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_autonomy_runtime.schemas.verified_command import current_time_ms


class RobotStateSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_robot: str = Field(min_length=1)
    observed_at_ms: int = Field(default_factory=current_time_ms, ge=0)
    cmd_vel_out_observed: bool | None = None
    odom_observed: bool | None = None
    emergency_stop_available: bool | None = None
    operator_armed: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

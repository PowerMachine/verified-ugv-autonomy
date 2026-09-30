from __future__ import annotations

import time
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_autonomy_runtime.schemas.common import make_id


def current_time_ms() -> int:
    return int(time.time() * 1000)


class VerifiedCommand(BaseModel):
    """A workstation-verified physical command candidate.

    This schema verifies shape and basic temporal consistency. The Jetson
    executor still performs the final deterministic safety checks before any
    ROS publish is attempted.
    """

    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(default_factory=lambda: make_id("vcmd"), min_length=1)
    sequence_id: int = Field(ge=0)
    created_at_ms: int = Field(ge=0)
    expires_at_ms: int = Field(ge=0)
    target_robot: str = Field(min_length=1)
    target_topic: str = Field(min_length=1)
    command_type: str = Field(min_length=1)
    linear_x: float
    angular_z: float
    duration_ms: int = Field(ge=0)
    max_linear_x: float = Field(gt=0)
    max_angular_z: float = Field(gt=0)
    requires_stop_after: bool
    operator_armed: bool
    approval_id: Optional[str] = None
    verifier_summary: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_time_window(self) -> "VerifiedCommand":
        if self.expires_at_ms <= self.created_at_ms:
            raise ValueError("expires_at_ms must be greater than created_at_ms")
        return self

    @property
    def ttl_ms(self) -> int:
        return self.expires_at_ms - self.created_at_ms

    def is_expired(self, now_ms: int | None = None) -> bool:
        return (now_ms if now_ms is not None else current_time_ms()) >= self.expires_at_ms

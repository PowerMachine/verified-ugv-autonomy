from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SafetyEnvelope(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    read_only: bool = True
    physical_execution_enabled: bool = False
    max_linear_mps: float = Field(default=0.1, gt=0)
    max_angular_radps: float = Field(default=0.2, gt=0)
    max_accel_mps2: float = Field(default=0.15, gt=0)
    default_ttl_ms: int = Field(default=500, gt=0)
    deadman_timeout_ms: int = Field(default=1000, gt=0)
    operator_armed: bool = False
    emergency_stop_available: bool = False
    geofence_enabled: bool = False
    obstacle_stop_enabled: bool = True
    require_operator_confirmation: bool = True
    operator_confirmed_safe_area: bool = False
    allowed_actions: list[str] = Field(
        default_factory=lambda: [
            "stop",
            "wait",
            "inspect_point",
            "return_home",
            "report_only",
            "primitive_sequence",
        ]
    )

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "SafetyEnvelope":
        return cls(**config.get("safety", config))

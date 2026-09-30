from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate, ActionType
from ai_autonomy_runtime.schemas.common import RiskLevel
from ai_autonomy_runtime.schemas.safety_envelope import SafetyEnvelope


class SafetyWrapperResult(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    accepted: bool
    reason: str
    checks: dict[str, bool] = Field(default_factory=dict)
    clamped_command: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SafeCommandWrapper:
    """Deterministic safety gate. It never publishes ROS commands."""

    def evaluate(
        self,
        candidate: ActionCandidate,
        envelope: SafetyEnvelope,
        require_physical_gate: bool = True,
    ) -> SafetyWrapperResult:
        action = _value(candidate.action_type)
        risk = _value(candidate.risk_level)
        checks: dict[str, bool] = {}
        command: dict[str, Any] = dict(candidate.parameters)

        checks["ttl"] = not candidate.is_expired()
        checks["ttl_exists"] = candidate.ttl_ms > 0
        checks["sequence_id"] = _sequence_id_valid(candidate.parameters.get("sequence_id"))
        checks["action_allow_list"] = action in set(envelope.allowed_actions)
        safe_initial_actions = {
            "stop",
            "wait",
            "inspect_point",
            "return_home",
            "report_only",
            "primitive_sequence",
        }
        checks["safe_initial_action"] = action in safe_initial_actions or (
            action == "velocity_candidate" and not require_physical_gate
        )
        checks["risk_level"] = risk not in {RiskLevel.CRITICAL.value}
        checks["deadman_timeout"] = envelope.deadman_timeout_ms > 0

        if action == ActionType.VELOCITY_CANDIDATE.value:
            command = self._clamp_velocity(command, envelope)
            checks["velocity_clamp"] = True
            checks["acceleration_clamp"] = abs(float(command.get("accel_mps2", 0.0))) <= envelope.max_accel_mps2
        else:
            checks["velocity_clamp"] = True
            checks["acceleration_clamp"] = True

        if envelope.geofence_enabled:
            checks["geofence"] = bool(candidate.parameters.get("inside_geofence", True))
        else:
            checks["geofence"] = True

        if envelope.obstacle_stop_enabled and bool(candidate.parameters.get("obstacle_detected", False)):
            checks["obstacle_stop"] = False
        else:
            checks["obstacle_stop"] = True

        if candidate.requires_physical_execution and require_physical_gate:
            checks["read_only_disabled"] = not envelope.read_only
            checks["physical_execution_enabled"] = envelope.physical_execution_enabled
            checks["env_physical_execution"] = os.environ.get("ENABLE_PHYSICAL_EXECUTION") == "1"
            checks["operator_armed"] = envelope.operator_armed
            checks["emergency_stop_available"] = envelope.emergency_stop_available
            if envelope.require_operator_confirmation:
                checks["operator_confirmed_safe_area"] = envelope.operator_confirmed_safe_area
            else:
                checks["operator_confirmed_safe_area"] = True
        else:
            checks["read_only_disabled"] = True
            checks["physical_execution_enabled"] = True
            checks["env_physical_execution"] = True
            checks["operator_armed"] = True
            checks["emergency_stop_available"] = True
            checks["operator_confirmed_safe_area"] = True

        failed = [name for name, passed in checks.items() if not passed]
        return SafetyWrapperResult(
            accepted=not failed,
            reason="ok" if not failed else f"failed safety checks: {', '.join(failed)}",
            checks=checks,
            clamped_command=command,
            metadata={"candidate_id": candidate.candidate_id, "action_type": action},
        )

    def _clamp_velocity(self, command: dict[str, Any], envelope: SafetyEnvelope) -> dict[str, Any]:
        linear_x = float(command.get("linear_x", 0.0))
        angular_z = float(command.get("angular_z", 0.0))
        accel = float(command.get("accel_mps2", 0.0))
        command["linear_x"] = max(-envelope.max_linear_mps, min(envelope.max_linear_mps, linear_x))
        command["angular_z"] = max(-envelope.max_angular_radps, min(envelope.max_angular_radps, angular_z))
        command["accel_mps2"] = max(-envelope.max_accel_mps2, min(envelope.max_accel_mps2, accel))
        return command


def _sequence_id_valid(value: Any) -> bool:
    if value is None:
        return True
    try:
        return int(value) >= 0
    except (TypeError, ValueError):
        return False


def _value(value: Any) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)

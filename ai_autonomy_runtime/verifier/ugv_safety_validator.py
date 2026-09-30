from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate, ActionType
from ai_autonomy_runtime.schemas.common import Severity
from ai_autonomy_runtime.schemas.verification_result import VerificationResult


@dataclass(frozen=True)
class UGVSafetyLimits:
    max_linear: float = 0.08
    max_angular: float = 0.15
    max_duration_ms: int = 1000
    requires_human_approval_for_physical: bool = True


class UGVSafetyValidator:
    name = "ugv_safety_validator"

    def __init__(self, limits: UGVSafetyLimits | None = None) -> None:
        self.limits = limits or UGVSafetyLimits()

    def validate(self, candidate: ActionCandidate, human_approved: bool = False) -> VerificationResult:
        start = time.perf_counter()
        action = str(candidate.action_type)
        motion = motion_parameters(candidate)
        checks = {
            "action_type_allowed": action in _ALLOWED_PREVIEW_ACTIONS,
            "ttl": not candidate.is_expired(),
            "duration_limit": 0 <= motion["duration_ms"] <= self.limits.max_duration_ms,
            "linear_limit": abs(float(motion["linear_x"])) <= self.limits.max_linear,
            "angular_limit": abs(float(motion["angular_z"])) <= self.limits.max_angular,
        }
        physical_requested = bool(candidate.requires_physical_execution)
        physical_approved = not (
            physical_requested and self.limits.requires_human_approval_for_physical and not human_approved
        )
        checks["physical_approval"] = physical_approved
        failed = [name for name, passed in checks.items() if not passed]
        executable = not failed and (not physical_requested or human_approved)
        return VerificationResult(
            checker_name=self.name,
            passed=not failed,
            reason="ok" if not failed else f"failed safety checks: {', '.join(failed)}",
            severity=Severity.INFO if not failed else Severity.WARNING,
            latency_ms=(time.perf_counter() - start) * 1000.0,
            metadata={
                "checks": checks,
                "limits": asdict(self.limits),
                "motion": motion,
                "executable": executable,
                "physical_requested": physical_requested,
                "human_approved": human_approved,
            },
        )


def motion_parameters(candidate: ActionCandidate) -> dict[str, Any]:
    action = str(candidate.action_type)
    params = dict(candidate.parameters)
    duration_ms = int(params.get("duration_ms", candidate.expected_duration_ms or 0))
    if action == ActionType.FORWARD.value:
        linear_x = abs(_float(params.get("linear_x", params.get("linear", 0.0))))
        angular_z = 0.0
    elif action == ActionType.BACKWARD.value:
        linear_x = -abs(_float(params.get("linear_x", params.get("linear", 0.0))))
        angular_z = 0.0
    elif action == ActionType.TURN_LEFT.value:
        linear_x = 0.0
        angular_z = abs(_float(params.get("angular_z", params.get("angular", 0.0))))
    elif action == ActionType.TURN_RIGHT.value:
        linear_x = 0.0
        angular_z = -abs(_float(params.get("angular_z", params.get("angular", 0.0))))
    elif action == ActionType.PRIMITIVE_SEQUENCE.value:
        sequence = params.get("sequence", [])
        return _sequence_motion_parameters(sequence)
    else:
        linear_x = 0.0
        angular_z = 0.0
    return {
        "linear_x": linear_x,
        "angular_z": angular_z,
        "duration_ms": duration_ms,
        "sequence": [],
    }


def _sequence_motion_parameters(sequence: Any) -> dict[str, Any]:
    if not isinstance(sequence, list):
        return {"linear_x": 0.0, "angular_z": 0.0, "duration_ms": 0, "sequence": []}
    total_duration = 0
    max_linear = 0.0
    max_angular = 0.0
    normalized: list[dict[str, Any]] = []
    for step in sequence:
        if not isinstance(step, dict):
            continue
        action = str(step.get("action", "wait"))
        duration_ms = int(step.get("duration_ms", 0))
        linear = abs(_float(step.get("linear_x", step.get("linear", 0.0))))
        angular = abs(_float(step.get("angular_z", step.get("angular", 0.0))))
        if action == "backward":
            linear = -linear
        if action == "turn_right":
            angular = -angular
        if action in {"turn_left", "turn_right"}:
            linear = 0.0
        if action in {"forward", "backward"}:
            angular = 0.0
        total_duration += max(0, duration_ms)
        max_linear = max(max_linear, abs(linear))
        max_angular = max(max_angular, abs(angular))
        normalized.append(
            {
                "action": action,
                "linear_x": linear,
                "angular_z": angular,
                "duration_ms": duration_ms,
            }
        )
    return {
        "linear_x": max_linear,
        "angular_z": max_angular,
        "duration_ms": total_duration,
        "sequence": normalized,
    }


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


_ALLOWED_PREVIEW_ACTIONS = {
    ActionType.STOP.value,
    ActionType.WAIT.value,
    ActionType.FORWARD.value,
    ActionType.BACKWARD.value,
    ActionType.TURN_LEFT.value,
    ActionType.TURN_RIGHT.value,
    ActionType.PRIMITIVE_SEQUENCE.value,
    ActionType.REPORT_ONLY.value,
}

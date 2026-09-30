from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ai_autonomy_runtime.live.ugv_live_state import parse_telemetry_line
from ai_autonomy_runtime.schemas.execution_receipt import ExecutionReceipt


OutcomeStatus = Literal["success", "partial", "anomaly", "exception_required"]


class OutcomeCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check: str
    passed: bool
    detail: str = ""
    critical: bool = True


class TwistObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available_samples: int = 0
    nonzero_samples: int = 0
    max_abs_linear_x: float = 0.0
    max_abs_angular_z: float = 0.0
    peak_linear_x: float = 0.0
    peak_angular_z: float = 0.0
    first_nonzero_sample_idx: int | None = None
    last_nonzero_sample_idx: int | None = None
    zero_after_nonzero: bool = False
    first_nonzero_samples: list[dict[str, Any]] = Field(default_factory=list)


class OutcomeReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: OutcomeStatus
    exception_required: bool
    reason: str
    command_id: str | None = None
    checks: list[OutcomeCheck]
    expected: dict[str, float | int | bool]
    observed: dict[str, Any]
    receipt: dict[str, Any] | None = None


def review_bounded_command_outcome(
    *,
    telemetry_log: str | Path,
    receipt: ExecutionReceipt | dict[str, Any],
    expected_linear_x: float,
    expected_angular_z: float,
    expected_duration_ms: int,
    linear_tolerance: float = 0.01,
    angular_tolerance: float = 0.02,
    zero_epsilon: float = 1e-6,
    require_cmd_out: bool = True,
    require_odom: bool = True,
    require_feedback: bool = True,
    require_stop: bool = True,
) -> OutcomeReview:
    resolved_receipt = receipt if isinstance(receipt, ExecutionReceipt) else ExecutionReceipt.model_validate(receipt)
    parsed = parse_telemetry_log(telemetry_log)
    states = parsed["states"]
    cmd_in = summarize_twist_observation(states, "cmd_in", zero_epsilon=zero_epsilon)
    cmd_out = summarize_twist_observation(states, "cmd_out", zero_epsilon=zero_epsilon)
    counts = [((state.get("status") or {}).get("topic_message_counts") or {}) for state in states]
    last_counts = counts[-1] if counts else {}

    expected = {
        "linear_x": float(expected_linear_x),
        "angular_z": float(expected_angular_z),
        "duration_ms": int(expected_duration_ms),
        "requires_stop_after": bool(require_stop),
    }
    checks = [
        OutcomeCheck(
            check="receipt_executed",
            passed=bool(resolved_receipt.accepted and resolved_receipt.executed and resolved_receipt.ros_published),
            detail=(
                f"accepted={resolved_receipt.accepted}, executed={resolved_receipt.executed}, "
                f"ros_published={resolved_receipt.ros_published}, publish_count={resolved_receipt.publish_count}"
            ),
        ),
        OutcomeCheck(
            check="telemetry_samples_present",
            passed=len(states) > 0,
            detail=f"sample_count={len(states)}",
        ),
        _expected_twist_check(
            "cmd_in_expected_observed",
            cmd_in,
            expected_linear_x,
            expected_angular_z,
            linear_tolerance,
            angular_tolerance,
        ),
        _expected_twist_check(
            "cmd_out_expected_observed",
            cmd_out,
            expected_linear_x,
            expected_angular_z,
            linear_tolerance,
            angular_tolerance,
            critical=require_cmd_out,
        ),
        OutcomeCheck(
            check="cmd_in_stop_observed",
            passed=(not require_stop) or cmd_in.zero_after_nonzero,
            detail=f"zero_after_nonzero={cmd_in.zero_after_nonzero}",
            critical=require_stop,
        ),
        OutcomeCheck(
            check="cmd_out_stop_observed",
            passed=(not require_stop) or cmd_out.zero_after_nonzero,
            detail=f"zero_after_nonzero={cmd_out.zero_after_nonzero}",
            critical=require_stop and require_cmd_out,
        ),
        OutcomeCheck(
            check="odom_available",
            passed=(not require_odom) or any((state.get("status") or {}).get("odom_available") for state in states),
            detail=f"odom_available_samples={sum(1 for state in states if (state.get('status') or {}).get('odom_available'))}",
            critical=require_odom,
        ),
        OutcomeCheck(
            check="feedback_available",
            passed=(not require_feedback) or any(isinstance(state.get("feedback"), dict) for state in states),
            detail=f"feedback_available_samples={sum(1 for state in states if isinstance(state.get('feedback'), dict))}",
            critical=require_feedback,
        ),
        OutcomeCheck(
            check="telemetry_malformed_lines",
            passed=len(parsed["malformed"]) == 0,
            detail=f"malformed_count={len(parsed['malformed'])}",
        ),
        OutcomeCheck(
            check="telemetry_error_events",
            passed=not _has_error_event(parsed["events"]),
            detail=f"event_count={len(parsed['events'])}",
            critical=False,
        ),
    ]

    failed_critical = [check.check for check in checks if check.critical and not check.passed]
    failed_noncritical = [check.check for check in checks if not check.critical and not check.passed]
    if failed_critical:
        status: OutcomeStatus = "exception_required" if _requires_exception(failed_critical) else "anomaly"
        reason = f"failed critical outcome checks: {', '.join(failed_critical)}"
    elif failed_noncritical:
        status = "partial"
        reason = f"failed noncritical outcome checks: {', '.join(failed_noncritical)}"
    else:
        status = "success"
        reason = "bounded command outcome matched expected telemetry"

    return OutcomeReview(
        status=status,
        exception_required=status == "exception_required",
        reason=reason,
        command_id=resolved_receipt.command_id,
        checks=checks,
        expected=expected,
        observed={
            "sample_count": len(states),
            "event_count": len(parsed["events"]),
            "ignored_line_count": parsed["ignored_line_count"],
            "malformed_line_count": len(parsed["malformed"]),
            "last_topic_message_counts": last_counts,
            "cmd_in": cmd_in.model_dump(mode="json"),
            "cmd_out": cmd_out.model_dump(mode="json"),
        },
        receipt=resolved_receipt.model_dump(mode="json"),
    )


def parse_telemetry_log(path: str | Path) -> dict[str, Any]:
    states: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    malformed: list[dict[str, str | None]] = []
    ignored = 0
    for line in Path(path).read_text(encoding="utf-8-sig", errors="replace").splitlines():
        parsed = parse_telemetry_line(line)
        if parsed.kind == "state" and parsed.payload is not None:
            states.append(parsed.payload)
        elif parsed.kind == "event" and parsed.payload is not None:
            events.append(parsed.payload)
        elif parsed.kind == "malformed":
            malformed.append({"line": parsed.raw_line, "error": parsed.error})
        elif parsed.kind == "ignored" and parsed.raw_line.strip():
            ignored += 1
    return {
        "states": states,
        "events": events,
        "malformed": malformed,
        "ignored_line_count": ignored,
    }


def summarize_twist_observation(
    states: list[dict[str, Any]],
    key: Literal["cmd_in", "cmd_out"],
    *,
    zero_epsilon: float = 1e-6,
) -> TwistObservation:
    available = 0
    nonzero = 0
    max_abs_linear = 0.0
    max_abs_angular = 0.0
    peak_linear = 0.0
    peak_angular = 0.0
    first_nonzero_idx: int | None = None
    last_nonzero_idx: int | None = None
    zero_after_nonzero = False
    samples: list[dict[str, Any]] = []

    for state in states:
        twist = state.get(key)
        if not isinstance(twist, dict):
            continue
        available += 1
        linear = _float(twist.get("linear_x"))
        angular = _float(twist.get("angular_z"))
        sample_idx = _int_or_none(state.get("sample_idx"))
        if abs(linear) > max_abs_linear:
            max_abs_linear = abs(linear)
            peak_linear = linear
        if abs(angular) > max_abs_angular:
            max_abs_angular = abs(angular)
            peak_angular = angular
        is_nonzero = abs(linear) > zero_epsilon or abs(angular) > zero_epsilon
        if is_nonzero:
            nonzero += 1
            if first_nonzero_idx is None:
                first_nonzero_idx = sample_idx
            last_nonzero_idx = sample_idx
            if len(samples) < 5:
                samples.append(
                    {
                        "sample_idx": sample_idx,
                        "wall_time": state.get("wall_time"),
                        "linear_x": linear,
                        "angular_z": angular,
                        "counts": (state.get("status") or {}).get("topic_message_counts"),
                    }
                )
        elif last_nonzero_idx is not None:
            zero_after_nonzero = True

    return TwistObservation(
        available_samples=available,
        nonzero_samples=nonzero,
        max_abs_linear_x=max_abs_linear,
        max_abs_angular_z=max_abs_angular,
        peak_linear_x=peak_linear,
        peak_angular_z=peak_angular,
        first_nonzero_sample_idx=first_nonzero_idx,
        last_nonzero_sample_idx=last_nonzero_idx,
        zero_after_nonzero=zero_after_nonzero,
        first_nonzero_samples=samples,
    )


def load_receipt(path: str | Path) -> ExecutionReceipt:
    return ExecutionReceipt.model_validate(json.loads(Path(path).read_text(encoding="utf-8-sig")))


def _expected_twist_check(
    name: str,
    observation: TwistObservation,
    expected_linear: float,
    expected_angular: float,
    linear_tolerance: float,
    angular_tolerance: float,
    *,
    critical: bool = True,
) -> OutcomeCheck:
    expected_nonzero = abs(expected_linear) > 1e-9 or abs(expected_angular) > 1e-9
    if expected_nonzero and observation.nonzero_samples <= 0:
        return OutcomeCheck(
            check=name,
            passed=False,
            detail="expected nonzero twist but observed none",
            critical=critical,
        )
    linear_ok = abs(observation.peak_linear_x - expected_linear) <= linear_tolerance
    angular_ok = abs(observation.peak_angular_z - expected_angular) <= angular_tolerance
    return OutcomeCheck(
        check=name,
        passed=linear_ok and angular_ok,
        detail=(
            f"expected=({expected_linear:.6f}, {expected_angular:.6f}), "
            f"observed_peak=({observation.peak_linear_x:.6f}, {observation.peak_angular_z:.6f}), "
            f"nonzero_samples={observation.nonzero_samples}"
        ),
        critical=critical,
    )


def _has_error_event(events: list[dict[str, Any]]) -> bool:
    return any(str(event.get("severity", "")).lower() == "error" for event in events)


def _requires_exception(failed_checks: list[str]) -> bool:
    return any(
        check
        in {
            "receipt_executed",
            "cmd_in_expected_observed",
            "cmd_out_expected_observed",
            "cmd_in_stop_observed",
            "cmd_out_stop_observed",
            "telemetry_malformed_lines",
        }
        for check in failed_checks
    )


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

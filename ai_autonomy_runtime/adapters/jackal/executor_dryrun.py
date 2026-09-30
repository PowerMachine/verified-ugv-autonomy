from __future__ import annotations

import time
from typing import Any

from pydantic import ValidationError

from ai_autonomy_runtime.adapters.jackal.executor_safety import (
    ExecutorSafetyConfig,
    SafetyEvaluation,
    evaluate_verified_command,
    last_sequence_for_command,
    load_executor_state,
    save_executor_state,
)
from ai_autonomy_runtime.schemas.execution_receipt import ExecutionReceipt
from ai_autonomy_runtime.schemas.verified_command import VerifiedCommand, current_time_ms


def dry_run_verified_command(
    payload: str | bytes | dict[str, Any] | VerifiedCommand,
    config: ExecutorSafetyConfig | None = None,
    state: dict[str, Any] | None = None,
    state_path: str | None = None,
    executor_armed_preview: bool = False,
    record_state_preview: bool = False,
    now_ms: int | None = None,
) -> tuple[ExecutionReceipt, SafetyEvaluation | None, VerifiedCommand | None]:
    """Run executor-equivalent safety checks without publishing ROS."""

    started_at_ms = current_time_ms()
    start_perf = time.perf_counter()
    command, schema_error = _parse_command(payload)
    if command is None:
        return (
            _receipt(
                command_id=_raw_field(payload, "command_id") or "unknown",
                accepted=False,
                rejected_reason=f"schema_validation_failed: {schema_error}",
                started_at_ms=started_at_ms,
                start_perf=start_perf,
            ),
            None,
            None,
        )

    resolved_config = config or ExecutorSafetyConfig.from_yaml()
    resolved_state = state if state is not None else load_executor_state(state_path) if state_path else {}
    evaluation = evaluate_verified_command(
        command,
        resolved_config,
        last_sequence_id=last_sequence_for_command(resolved_state, command),
        now_ms=now_ms,
        executor_armed=executor_armed_preview,
    )
    receipt = _receipt(
        command_id=command.command_id,
        accepted=evaluation.accepted,
        rejected_reason=evaluation.rejected_reason,
        started_at_ms=started_at_ms,
        start_perf=start_perf,
    )
    if receipt.accepted and record_state_preview and state_path:
        save_executor_state(state_path, command)
    return receipt, evaluation, command


def _parse_command(payload: str | bytes | dict[str, Any] | VerifiedCommand) -> tuple[VerifiedCommand | None, str | None]:
    try:
        if isinstance(payload, VerifiedCommand):
            return payload, None
        if isinstance(payload, bytes):
            return VerifiedCommand.model_validate_json(payload.decode("utf-8")), None
        if isinstance(payload, str):
            return VerifiedCommand.model_validate_json(payload), None
        return VerifiedCommand.model_validate(payload), None
    except (ValidationError, ValueError) as exc:
        return None, str(exc)


def _receipt(
    command_id: str,
    accepted: bool,
    rejected_reason: str | None,
    started_at_ms: int,
    start_perf: float,
) -> ExecutionReceipt:
    return ExecutionReceipt(
        command_id=command_id,
        accepted=accepted,
        executed=False,
        publish_disabled=True,
        ros_published=False,
        rejected_reason=rejected_reason,
        publish_topic=None,
        publish_count=0,
        stop_published=False,
        executor_latency_ms=(time.perf_counter() - start_perf) * 1000.0,
        cmd_vel_out_observed=None,
        odom_observed=None,
        started_at_ms=started_at_ms,
        finished_at_ms=current_time_ms(),
    )


def _raw_field(payload: Any, field: str) -> str | None:
    if isinstance(payload, dict):
        value = payload.get(field)
        return str(value) if value is not None else None
    if isinstance(payload, VerifiedCommand):
        value = getattr(payload, field, None)
        return str(value) if value is not None else None
    return None

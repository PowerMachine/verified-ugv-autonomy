from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ai_autonomy_runtime.adapters.jackal.executor_dryrun import dry_run_verified_command
from ai_autonomy_runtime.adapters.jackal.executor_safety import ExecutorSafetyConfig, evaluate_verified_command
from ai_autonomy_runtime.sandbox.ugv_2d_simulator import UGV2DSimulator, write_map_html, write_path_csv
from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate
from ai_autonomy_runtime.schemas.common import RiskLevel
from ai_autonomy_runtime.schemas.operator_approval import OperatorApproval
from ai_autonomy_runtime.schemas.verified_command import VerifiedCommand, current_time_ms
from ai_autonomy_runtime.verifier.ugv_safety_validator import UGVSafetyValidator, motion_parameters


def main() -> None:
    parser = argparse.ArgumentParser(description="Preview ActionCandidate -> OperatorApproval -> VerifiedCommand without publishing.")
    parser.add_argument("--action", required=True)
    parser.add_argument("--linear", type=float, default=0.0)
    parser.add_argument("--angular", type=float, default=0.0)
    parser.add_argument("--duration-ms", type=int, default=0)
    parser.add_argument("--max-linear", type=float, default=0.08)
    parser.add_argument("--max-angular", type=float, default=0.15)
    parser.add_argument("--output", default=None)
    parser.add_argument("--operator-id", default="manual_operator")
    parser.add_argument("--operator-approved", action="store_true")
    parser.add_argument("--sequence-id", type=int, default=1)
    parser.add_argument("--target-robot", default="jackal")
    parser.add_argument("--target-topic", default="/cmd_vel")
    parser.add_argument(
        "--executor-armed-preview",
        action="store_true",
        help="Evaluate the final executor arming check as if the executor CLI was armed. Still never publishes.",
    )
    args = parser.parse_args()

    summary = run_preview_bridge(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["accepted"]:
        raise SystemExit(2)


def run_preview_bridge(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output or Path("local_outputs") / "verified_command_preview" / _timestamp())
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        candidate = _candidate_from_args(args)
    except (ValidationError, ValueError) as exc:
        summary = _base_summary(output_dir, accepted=False, reason=f"candidate_schema_failed: {exc}")
        _write_json(output_dir / "summary.json", summary)
        return summary

    _write_json(output_dir / "action_candidate.json", candidate.model_dump(mode="json"))
    approval = OperatorApproval(
        operator_id=args.operator_id,
        approved=bool(args.operator_approved),
        scope={
            "candidate_id": candidate.candidate_id,
            "action_type": str(candidate.action_type),
            "target_robot": args.target_robot,
            "target_topic": args.target_topic,
            "duration_ms": args.duration_ms,
        },
        notes="preview-only approval record; no ROS publish performed",
    )
    _write_json(output_dir / "operator_approval.json", approval.model_dump(mode="json"))

    verification = UGVSafetyValidator().validate(candidate, human_approved=approval.approved)
    _write_json(output_dir / "verification_result.json", verification.model_dump(mode="json"))

    points = _simulate(candidate)
    trajectory_csv = write_path_csv(output_dir / "preview_trajectory.csv", points)
    preview_map = write_map_html(output_dir / "preview_map.html", points, _summary_for(points))

    verified_command = None
    executor_safety = None
    executor_dryrun_receipt = None
    accepted = verification.passed
    reason = verification.reason
    if accepted:
        verified_command = _verified_command_from_candidate(candidate, approval, args, verification)
        _write_json(output_dir / "verified_command.json", verified_command.model_dump(mode="json"))
        executor_safety = evaluate_verified_command(
            verified_command,
            ExecutorSafetyConfig(),
            executor_armed=False,
        )
        _write_json(output_dir / "executor_safety_preview.json", executor_safety.model_dump(mode="json"))
        executor_dryrun_receipt, executor_dryrun_safety, _ = dry_run_verified_command(
            verified_command,
            config=ExecutorSafetyConfig(),
            executor_armed_preview=bool(args.executor_armed_preview),
        )
        _write_json(output_dir / "executor_dryrun_receipt.json", executor_dryrun_receipt.model_dump(mode="json"))
        if executor_dryrun_safety is not None:
            _write_json(output_dir / "executor_dryrun_safety.json", executor_dryrun_safety.model_dump(mode="json"))
    else:
        _write_json(output_dir / "verified_command.json", {"created": False, "reason": reason})

    summary = {
        **_base_summary(output_dir, accepted=accepted, reason=reason),
        "action_candidate": str(output_dir / "action_candidate.json"),
        "operator_approval": str(output_dir / "operator_approval.json"),
        "verification_result": str(output_dir / "verification_result.json"),
        "verified_command": str(output_dir / "verified_command.json"),
        "executor_safety_preview": str(output_dir / "executor_safety_preview.json") if executor_safety else None,
        "executor_dryrun_receipt": str(output_dir / "executor_dryrun_receipt.json") if executor_dryrun_receipt else None,
        "executor_dryrun_safety": str(output_dir / "executor_dryrun_safety.json") if executor_dryrun_receipt else None,
        "preview_trajectory_csv": str(trajectory_csv),
        "preview_map_html": str(preview_map),
        "operator_approved": approval.approved,
        "verified_command_created": verified_command is not None,
        "executor_would_execute_without_cli_armed": bool(executor_safety.accepted) if executor_safety else False,
        "executor_armed_preview": bool(args.executor_armed_preview),
        "executor_dryrun_accepted": bool(executor_dryrun_receipt.accepted) if executor_dryrun_receipt else False,
        "executor_dryrun_executed": bool(executor_dryrun_receipt.executed) if executor_dryrun_receipt else False,
        "publish_disabled": True,
        "ros_published": False,
        "ssh_used": False,
        "llm_used": False,
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


def _candidate_from_args(args: argparse.Namespace) -> ActionCandidate:
    return ActionCandidate(
        source="manual",
        candidate_type="ugv_motion",
        action_type=args.action,
        parameters={
            "linear": args.linear,
            "angular": args.angular,
            "duration_ms": args.duration_ms,
        },
        expected_duration_ms=args.duration_ms,
        ttl_ms=max(1000, args.duration_ms + 500),
        risk_level=RiskLevel.LOW,
        requires_physical_execution=True,
        reason="manual bridge preview",
    )


def _verified_command_from_candidate(
    candidate: ActionCandidate,
    approval: OperatorApproval,
    args: argparse.Namespace,
    verification: Any,
) -> VerifiedCommand:
    motion = motion_parameters(candidate)
    created_at_ms = current_time_ms()
    return VerifiedCommand(
        sequence_id=args.sequence_id,
        created_at_ms=created_at_ms,
        expires_at_ms=created_at_ms + 800,
        target_robot=args.target_robot,
        target_topic=args.target_topic,
        command_type="velocity_primitive",
        linear_x=float(motion["linear_x"]),
        angular_z=float(motion["angular_z"]),
        duration_ms=int(motion["duration_ms"]),
        max_linear_x=float(getattr(args, "max_linear", 0.08)),
        max_angular_z=float(getattr(args, "max_angular", 0.15)),
        requires_stop_after=True,
        operator_armed=approval.approved,
        approval_id=approval.approval_id,
        verifier_summary={
            "candidate_id": candidate.candidate_id,
            "verification_result_id": verification.result_id,
            "preview_only": True,
        },
    )


def _simulate(candidate: ActionCandidate) -> list[Any]:
    simulator = UGV2DSimulator()
    motion = motion_parameters(candidate)
    simulator.run_fixed(
        float(motion["linear_x"]),
        float(motion["angular_z"]),
        max(0.0, int(motion["duration_ms"]) / 1000.0),
        dt_s=0.05,
    )
    return simulator.path


def _summary_for(points: list[Any]) -> dict[str, float | int]:
    simulator = UGV2DSimulator()
    simulator.path = points
    if points:
        simulator.pose.t_s = points[-1].t_s
        simulator.pose.x_m = points[-1].x_m
        simulator.pose.y_m = points[-1].y_m
        simulator.pose.yaw_rad = points[-1].yaw_rad
    return simulator.summary()


def _base_summary(output_dir: Path, accepted: bool, reason: str) -> dict[str, Any]:
    return {
        "accepted": accepted,
        "reason": reason,
        "output_dir": str(output_dir),
        "bridge_stage": "preview_only",
        "physical_execution_connected": False,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    main()

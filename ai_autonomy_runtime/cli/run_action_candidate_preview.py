from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ai_autonomy_runtime.sandbox.ugv_2d_simulator import UGV2DSimulator, write_map_html, write_path_csv
from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate
from ai_autonomy_runtime.schemas.common import RiskLevel
from ai_autonomy_runtime.verifier.ugv_safety_validator import UGVSafetyValidator, motion_parameters


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and verify a dry-run UGV ActionCandidate preview.")
    parser.add_argument("--action", required=True)
    parser.add_argument("--linear", type=float, default=0.0)
    parser.add_argument("--angular", type=float, default=0.0)
    parser.add_argument("--duration-ms", type=int, default=0)
    parser.add_argument("--sequence-json", help="Primitive sequence JSON list for --action primitive_sequence.")
    parser.add_argument("--output", default=None)
    parser.add_argument("--source", default="manual")
    parser.add_argument("--reason", default="manual dry-run preview")
    parser.add_argument("--requires-physical-execution", action="store_true")
    parser.add_argument("--human-approved", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output or Path("local_outputs") / "action_preview" / _timestamp())
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        candidate = _candidate_from_args(args)
    except (ValidationError, ValueError) as exc:
        summary = {
            "accepted": False,
            "reason": str(exc),
            "output_dir": str(output_dir),
            "ros_published": False,
            "ssh_used": False,
            "llm_used": False,
        }
        _write_json(output_dir / "summary.json", summary)
        raise SystemExit(f"ActionCandidate rejected by schema: {exc}") from exc

    _write_json(output_dir / "action_candidate.json", candidate.model_dump(mode="json"))
    verification = UGVSafetyValidator().validate(candidate, human_approved=args.human_approved)
    _write_json(output_dir / "verification_result.json", verification.model_dump(mode="json"))
    points = _simulate_preview(candidate) if verification.passed else UGV2DSimulator().path
    trajectory_csv = write_path_csv(output_dir / "preview_trajectory.csv", points)
    preview_map = write_map_html(output_dir / "preview_map.html", points, _summary_for(points))
    summary = {
        "accepted": verification.passed,
        "reason": verification.reason,
        "executable": bool(verification.metadata.get("executable", False)),
        "output_dir": str(output_dir),
        "action_candidate": str(output_dir / "action_candidate.json"),
        "verification_result": str(output_dir / "verification_result.json"),
        "preview_trajectory_csv": str(trajectory_csv),
        "preview_map_html": str(preview_map),
        "ros_published": False,
        "ssh_used": False,
        "llm_used": False,
    }
    _write_json(output_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not verification.passed:
        raise SystemExit(2)


def _candidate_from_args(args: argparse.Namespace) -> ActionCandidate:
    parameters: dict[str, Any] = {
        "linear": args.linear,
        "angular": args.angular,
        "duration_ms": args.duration_ms,
    }
    if args.sequence_json:
        loaded = json.loads(args.sequence_json)
        if not isinstance(loaded, list):
            raise ValueError("--sequence-json must be a JSON list")
        parameters["sequence"] = loaded
    return ActionCandidate(
        source=args.source,
        candidate_type="ugv_motion",
        action_type=args.action,
        parameters=parameters,
        expected_duration_ms=args.duration_ms,
        ttl_ms=max(1000, args.duration_ms + 500),
        risk_level=RiskLevel.LOW,
        requires_physical_execution=args.requires_physical_execution,
        reason=args.reason,
    )


def _simulate_preview(candidate: ActionCandidate) -> list[Any]:
    simulator = UGV2DSimulator()
    motion = motion_parameters(candidate)
    sequence = motion.get("sequence") or []
    if sequence:
        for step in sequence:
            simulator.run_fixed(
                float(step["linear_x"]),
                float(step["angular_z"]),
                max(0.0, int(step["duration_ms"]) / 1000.0),
                dt_s=0.05,
            )
        return simulator.path
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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    main()

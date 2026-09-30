from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ai_autonomy_runtime.adapters.jackal.physical_readiness import readiness_report_allows_physical_execution
from ai_autonomy_runtime.adapters.jackal.verified_executor import VerifiedExecutor
from ai_autonomy_runtime.core.audit_logger import _to_jsonable
from ai_autonomy_runtime.schemas.execution_receipt import ExecutionReceipt
from ai_autonomy_runtime.schemas.verified_command import current_time_ms


def main() -> None:
    parser = argparse.ArgumentParser(description="Jetson-side safety-gated VerifiedCommand executor.")
    parser.add_argument("--config", default="configs/jackal_executor_safety.yaml")
    parser.add_argument("--state-file", default="runs/executor_state.json")
    parser.add_argument("--runs-dir", default="runs")
    parser.add_argument("--armed", action="store_true", help="Required before any ROS /cmd_vel publish.")
    parser.add_argument(
        "--readiness-report",
        default=None,
        help="Required with --armed. Must be a ready limited physical readiness review JSON.",
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input-json", help="VerifiedCommand JSON, or '-' to read stdin.")
    input_group.add_argument("--input-file", help="Path to a VerifiedCommand JSON file.")
    args = parser.parse_args()

    if args.input_json is not None:
        payload = sys.stdin.read() if args.input_json == "-" else args.input_json
    else:
        payload = Path(args.input_file).read_text(encoding="utf-8")

    if args.armed:
        allowed, reason = readiness_report_allows_physical_execution(args.readiness_report) if args.readiness_report else (
            False,
            "limited_physical_readiness_report_required",
        )
        if not allowed:
            receipt = _blocked_receipt(payload, reason)
            sys.stdout.write(json.dumps(_to_jsonable(receipt), ensure_ascii=False, sort_keys=True))
            sys.stdout.write("\n")
            raise SystemExit(2)

    executor = VerifiedExecutor(
        config_path=args.config,
        state_path=args.state_file,
        runs_dir=args.runs_dir,
    )
    receipt = executor.execute(payload, armed=args.armed)
    sys.stdout.write(json.dumps(_to_jsonable(receipt), ensure_ascii=False, sort_keys=True))
    sys.stdout.write("\n")


def _blocked_receipt(payload: str, reason: str) -> ExecutionReceipt:
    now_ms = current_time_ms()
    return ExecutionReceipt(
        command_id=_raw_command_id(payload),
        accepted=False,
        executed=False,
        publish_disabled=True,
        ros_published=False,
        rejected_reason=reason,
        publish_topic=None,
        publish_count=0,
        stop_published=False,
        executor_latency_ms=0.0,
        cmd_vel_out_observed=None,
        odom_observed=None,
        started_at_ms=now_ms,
        finished_at_ms=now_ms,
    )


def _raw_command_id(payload: str) -> str:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return "unknown"
    value = data.get("command_id") if isinstance(data, dict) else None
    return str(value) if value is not None else "unknown"


if __name__ == "__main__":
    main()

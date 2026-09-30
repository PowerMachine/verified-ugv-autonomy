from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_autonomy_runtime.adapters.jackal.executor_dryrun import dry_run_verified_command
from ai_autonomy_runtime.adapters.jackal.executor_safety import ExecutorSafetyConfig
from ai_autonomy_runtime.core.audit_logger import _to_jsonable
from ai_autonomy_runtime.schemas.execution_receipt import ExecutionReceipt
from ai_autonomy_runtime.schemas.verified_command import current_time_ms


EXECUTOR_RECEIPT_PREFIX = "UGV_EXECUTOR_RECEIPT_JSON "
EXECUTOR_EVENT_PREFIX = "UGV_EXECUTOR_EVENT_JSON "


def main() -> None:
    parser = argparse.ArgumentParser(description="Run executor-equivalent VerifiedCommand checks without ROS publish.")
    parser.add_argument("--config", default="configs/jackal_executor_safety.yaml")
    parser.add_argument("--state-file", default=None, help="Optional executor state file for replay checks.")
    parser.add_argument("--output", default=None)
    parser.add_argument("--executor-armed-preview", action="store_true")
    parser.add_argument(
        "--record-dryrun-state-preview",
        action="store_true",
        help="Record accepted dry-run sequence state for replay testing only.",
    )
    parser.add_argument(
        "--emit-prefixed-receipt",
        action="store_true",
        help="Emit UGV_EXECUTOR_* prefixed JSON lines for SSH transport parsing.",
    )
    parser.add_argument(
        "--refresh-time-window-preview",
        action="store_true",
        help="Refresh created/expires timestamps for dry-run inspection only. Never use as a physical execution shortcut.",
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input-json", help="VerifiedCommand JSON, or '-' to read stdin.")
    input_group.add_argument("--input-file", help="Path to a VerifiedCommand JSON file.")
    args = parser.parse_args()

    try:
        summary = run_executor_dryrun(args)
    except Exception as exc:
        if args.emit_prefixed_receipt:
            receipt = _exception_receipt(str(exc))
            _print_prefixed_event({"event_type": "dryrun_exception", "severity": "error", "message": str(exc)})
            _print_prefixed_receipt(receipt.model_dump(mode="json"))
            raise SystemExit(2) from exc
        raise
    if args.emit_prefixed_receipt:
        _print_prefixed_event(
            {
                "event_type": "dryrun_completed",
                "severity": "info",
                "time_ms": current_time_ms(),
                "accepted": summary["accepted"],
                "executed": summary["executed"],
                "time_window_refresh": summary.get("time_window_refresh"),
            }
        )
        _print_prefixed_receipt(summary["receipt"])
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["accepted"]:
        raise SystemExit(2)


def run_executor_dryrun(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output or Path("local_outputs") / "executor_dryrun" / _timestamp())
    output_dir.mkdir(parents=True, exist_ok=True)
    config = ExecutorSafetyConfig.from_yaml(args.config)
    payload = _read_payload(args)
    time_window_refresh: dict[str, Any] | None = None
    if args.refresh_time_window_preview:
        payload, time_window_refresh = _refresh_time_window(payload, config.command_ttl_ms)
    receipt, evaluation, command = dry_run_verified_command(
        payload,
        config=config,
        state_path=args.state_file,
        executor_armed_preview=args.executor_armed_preview,
        record_state_preview=bool(getattr(args, "record_dryrun_state_preview", False)),
    )
    if command is not None:
        _write_json(output_dir / "verified_command.json", command.model_dump(mode="json"))
    receipt_payload = receipt.model_dump(mode="json")
    _write_json(output_dir / "execution_receipt.json", receipt_payload)
    if evaluation is not None:
        _write_json(output_dir / "executor_safety_evaluation.json", evaluation.model_dump(mode="json"))
    summary = {
        "accepted": receipt.accepted,
        "executed": receipt.executed,
        "receipt": receipt_payload,
        "rejected_reason": receipt.rejected_reason,
        "output_dir": str(output_dir),
        "execution_receipt": str(output_dir / "execution_receipt.json"),
        "executor_safety_evaluation": str(output_dir / "executor_safety_evaluation.json") if evaluation else None,
        "verified_command": str(output_dir / "verified_command.json") if command else None,
        "executor_armed_preview": bool(args.executor_armed_preview),
        "record_dryrun_state_preview": bool(getattr(args, "record_dryrun_state_preview", False)),
        "dryrun_state_recorded": bool(
            getattr(args, "record_dryrun_state_preview", False) and receipt.accepted and command is not None and args.state_file
        ),
        "time_window_refreshed_for_preview": bool(args.refresh_time_window_preview),
        "time_window_refresh": time_window_refresh,
        "dry_run": True,
        "publish_disabled": receipt.publish_disabled,
        "ros_published": receipt.ros_published,
        "ssh_used": False,
        "llm_used": False,
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


def _read_payload(args: argparse.Namespace) -> str:
    if args.input_json is not None:
        if args.input_json == "-":
            import sys

            return sys.stdin.read()
        return args.input_json
    return Path(args.input_file).read_text(encoding="utf-8")


def _refresh_time_window(payload: str, ttl_ms: int) -> tuple[str, dict[str, Any]]:
    data = json.loads(payload)
    if not isinstance(data, dict):
        return payload, {
            "refreshed": False,
            "reason": "remote_dryrun_transport_preview",
            "error": "payload is not a JSON object",
        }
    original_created_at_ms = data.get("created_at_ms")
    original_expires_at_ms = data.get("expires_at_ms")
    now_ms = current_time_ms()
    data["created_at_ms"] = now_ms
    data["expires_at_ms"] = now_ms + ttl_ms
    return json.dumps(data, ensure_ascii=False), {
        "refreshed": True,
        "reason": "remote_dryrun_transport_preview",
        "original_created_at_ms": original_created_at_ms,
        "original_expires_at_ms": original_expires_at_ms,
        "refreshed_created_at_ms": data["created_at_ms"],
        "refreshed_expires_at_ms": data["expires_at_ms"],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(_to_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _print_prefixed_event(payload: dict[str, Any]) -> None:
    sys.stdout.write(EXECUTOR_EVENT_PREFIX)
    sys.stdout.write(json.dumps(_to_jsonable(payload), ensure_ascii=False, sort_keys=True))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _print_prefixed_receipt(payload: dict[str, Any]) -> None:
    sys.stdout.write(EXECUTOR_RECEIPT_PREFIX)
    sys.stdout.write(json.dumps(_to_jsonable(payload), ensure_ascii=False, sort_keys=True))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _exception_receipt(reason: str) -> ExecutionReceipt:
    now_ms = current_time_ms()
    return ExecutionReceipt(
        command_id="unknown",
        accepted=False,
        executed=False,
        publish_disabled=True,
        ros_published=False,
        rejected_reason=f"executor_dryrun_exception: {reason}",
        publish_topic=None,
        publish_count=0,
        stop_published=False,
        executor_latency_ms=0.0,
        cmd_vel_out_observed=None,
        odom_observed=None,
        started_at_ms=now_ms,
        finished_at_ms=now_ms,
    )


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    main()

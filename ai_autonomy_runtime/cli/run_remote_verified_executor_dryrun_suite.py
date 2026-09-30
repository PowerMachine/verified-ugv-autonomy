from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_autonomy_runtime.adapters.jackal.ssh_executor_dryrun_bridge import (
    RemoteExecutorDryRunConfig,
    RemoteExecutorDryRunResult,
    run_remote_executor_dryrun,
)
from ai_autonomy_runtime.cli.run_remote_verified_executor_dryrun import (
    _default_identity_file,
    _sync_remote_dryrun_code,
    _time_window_refresh_from_events,
    _write_json,
    _write_jsonl,
)


@dataclass
class SuiteStep:
    case_id: str
    step_id: str
    description: str
    command: dict[str, Any]
    executor_armed_preview: bool
    refresh_time_window_preview: bool
    expect_accepted: bool
    expect_reason_contains: str | None = None
    remote_state_file: str | None = None
    record_dryrun_state_preview: bool = False


def main() -> None:
    parser = argparse.ArgumentParser(description="Run remote VerifiedCommand dry-run negative checks over SSH.")
    parser.add_argument("--host", default="192.0.2.10")
    parser.add_argument("--user", default="robot")
    parser.add_argument("--remote-project-dir", default="/home/robot/ai-autonomy-ugv")
    parser.add_argument("--identity-file", default=_default_identity_file())
    parser.add_argument("--remote-config", default="configs/jackal_executor_safety.yaml")
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--suite-id", default=None)
    parser.add_argument("--ssh-connect-timeout", type=int, default=30)
    parser.add_argument("--executor-timeout", type=int, default=30)
    parser.add_argument("--skip-code-sync", action="store_true")
    args = parser.parse_args()

    summary = run_remote_executor_dryrun_suite(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["suite_passed"]:
        raise SystemExit(2)


def run_remote_executor_dryrun_suite(args: argparse.Namespace) -> dict[str, Any]:
    suite_id = args.suite_id or _timestamp()
    output_dir = Path(args.output or Path("local_outputs") / "remote_executor_dryrun_suite" / suite_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    base_command = json.loads(Path(args.input_file).read_text(encoding="utf-8"))
    if not isinstance(base_command, dict):
        raise ValueError("Expected input VerifiedCommand JSON object.")
    _write_json(output_dir / "base_verified_command.json", base_command)

    code_sync: dict[str, Any] = {"enabled": not args.skip_code_sync, "ok": True, "error": None}
    if not args.skip_code_sync:
        code_sync = _sync_remote_dryrun_code(args)

    config = RemoteExecutorDryRunConfig(
        host=args.host,
        user=args.user,
        remote_project_dir=args.remote_project_dir,
        identity_file=args.identity_file,
        executor_config=args.remote_config,
        ssh_connect_timeout_s=args.ssh_connect_timeout,
        executor_timeout_s=args.executor_timeout,
    )

    state_scope = f"{suite_id}_{_timestamp()}"
    steps = build_suite_steps(base_command, state_scope)
    results: list[dict[str, Any]] = []
    for step in steps:
        step_dir = output_dir / "cases" / f"{step.case_id}_{step.step_id}"
        results.append(_run_suite_step(step, step_dir, config))

    suite_passed = bool(code_sync.get("ok", False)) and all(item["passed"] for item in results)
    suite_passed = suite_passed and not any(item["observed"]["executed"] for item in results)
    suite_passed = suite_passed and not any(item["observed"]["ros_published"] for item in results)
    suite_passed = suite_passed and all(item["observed"]["publish_disabled"] for item in results)

    summary = {
        "suite_id": suite_id,
        "state_scope": state_scope,
        "suite_passed": suite_passed,
        "case_count": len(results),
        "passed_count": sum(1 for item in results if item["passed"]),
        "failed_count": sum(1 for item in results if not item["passed"]),
        "output_dir": str(output_dir),
        "base_verified_command": str(output_dir / "base_verified_command.json"),
        "code_sync": code_sync,
        "dry_run": True,
        "ssh_used": True,
        "llm_used": False,
        "manual_teleop_invoked": False,
        "physical_execution_connected": False,
        "executed_any": any(item["observed"]["executed"] for item in results),
        "ros_published_any": any(item["observed"]["ros_published"] for item in results),
        "publish_disabled_all": all(item["observed"]["publish_disabled"] for item in results),
        "cases": results,
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


def build_suite_steps(base_command: dict[str, Any], suite_id: str) -> list[SuiteStep]:
    replay_state_file = f"/tmp/ai_autonomy_remote_dryrun_suite_{_safe_slug(suite_id)}_replay_state.json"
    replay_command = _case_command(base_command, "replay_sequence", 600)
    return [
        SuiteStep(
            case_id="valid",
            step_id="accept",
            description="Valid command should be accepted in remote dry-run.",
            command=_case_command(base_command, "valid", 100),
            executor_armed_preview=True,
            refresh_time_window_preview=True,
            expect_accepted=True,
        ),
        SuiteStep(
            case_id="expired_without_refresh",
            step_id="reject",
            description="Expired command without refresh should be rejected.",
            command=_case_command(
                base_command,
                "expired_without_refresh",
                200,
                created_at_ms=1000,
                expires_at_ms=1600,
            ),
            executor_armed_preview=True,
            refresh_time_window_preview=False,
            expect_accepted=False,
            expect_reason_contains="ttl_not_expired",
        ),
        SuiteStep(
            case_id="over_limit_velocity",
            step_id="reject",
            description="Over-limit linear velocity should be rejected.",
            command=_case_command(base_command, "over_limit_velocity", 300, linear_x=0.5),
            executor_armed_preview=True,
            refresh_time_window_preview=True,
            expect_accepted=False,
            expect_reason_contains="linear_velocity_limit",
        ),
        SuiteStep(
            case_id="wrong_topic",
            step_id="reject",
            description="Topic outside the allow-list should be rejected.",
            command=_case_command(
                base_command,
                "wrong_topic",
                400,
                target_topic="/jackal_velocity_controller/cmd_vel",
            ),
            executor_armed_preview=True,
            refresh_time_window_preview=True,
            expect_accepted=False,
            expect_reason_contains="topic_allow_list",
        ),
        SuiteStep(
            case_id="missing_operator_approval",
            step_id="reject",
            description="Missing operator approval id should be rejected.",
            command=_case_command(base_command, "missing_operator_approval", 500, approval_id=None),
            executor_armed_preview=True,
            refresh_time_window_preview=True,
            expect_accepted=False,
            expect_reason_contains="operator_approval_id_present",
        ),
        SuiteStep(
            case_id="missing_executor_armed",
            step_id="reject",
            description="Missing executor armed preview flag should be rejected.",
            command=_case_command(base_command, "missing_executor_armed", 550),
            executor_armed_preview=False,
            refresh_time_window_preview=True,
            expect_accepted=False,
            expect_reason_contains="executor_cli_armed",
        ),
        SuiteStep(
            case_id="replay_sequence",
            step_id="record_first",
            description="First replay test command records dry-run sequence state.",
            command=dict(replay_command),
            executor_armed_preview=True,
            refresh_time_window_preview=True,
            expect_accepted=True,
            remote_state_file=replay_state_file,
            record_dryrun_state_preview=True,
        ),
        SuiteStep(
            case_id="replay_sequence",
            step_id="replay_second",
            description="Second command with the same sequence id should be rejected.",
            command=dict(replay_command),
            executor_armed_preview=True,
            refresh_time_window_preview=True,
            expect_accepted=False,
            expect_reason_contains="sequence_not_replayed",
            remote_state_file=replay_state_file,
        ),
    ]


def _run_suite_step(
    step: SuiteStep,
    step_dir: Path,
    base_config: RemoteExecutorDryRunConfig,
) -> dict[str, Any]:
    step_dir.mkdir(parents=True, exist_ok=True)
    _write_json(step_dir / "input_verified_command.json", step.command)
    config = base_config.model_copy(update={"state_file": step.remote_state_file})
    result = run_remote_executor_dryrun(
        json.dumps(step.command, ensure_ascii=False),
        config,
        executor_armed_preview=step.executor_armed_preview,
        refresh_time_window_preview=step.refresh_time_window_preview,
        record_dryrun_state_preview=step.record_dryrun_state_preview,
    )
    receipt_payload = result.receipt.model_dump(mode="json")
    _write_json(step_dir / "remote_execution_receipt.json", receipt_payload)
    _write_jsonl(step_dir / "remote_executor_events.jsonl", result.events)
    (step_dir / "raw_ssh_stdout.log").write_text(result.raw_stdout, encoding="utf-8")
    (step_dir / "raw_ssh_stderr.log").write_text(result.raw_stderr, encoding="utf-8")

    passed, failure_reason = suite_step_passed(step, result)
    summary = {
        "case_id": step.case_id,
        "step_id": step.step_id,
        "description": step.description,
        "passed": passed,
        "failure_reason": failure_reason,
        "expected": {
            "accepted": step.expect_accepted,
            "rejected_reason_contains": step.expect_reason_contains,
        },
        "observed": {
            "accepted": result.receipt.accepted,
            "executed": result.receipt.executed,
            "publish_disabled": result.receipt.publish_disabled,
            "ros_published": result.receipt.ros_published,
            "rejected_reason": result.receipt.rejected_reason,
        },
        "prefixed_receipt_parsed": result.prefixed_receipt_parsed,
        "prefixed_event_count": len(result.events),
        "malformed_protocol_lines": result.malformed_protocol_lines,
        "remote_returncode": result.returncode,
        "remote_state_file": step.remote_state_file,
        "record_dryrun_state_preview": step.record_dryrun_state_preview,
        "time_window_refreshed_for_preview": step.refresh_time_window_preview,
        "time_window_refresh": _time_window_refresh_from_events(result.events),
        "output_dir": str(step_dir),
        "remote_execution_receipt": str(step_dir / "remote_execution_receipt.json"),
        "raw_ssh_stdout": str(step_dir / "raw_ssh_stdout.log"),
        "raw_ssh_stderr": str(step_dir / "raw_ssh_stderr.log"),
    }
    _write_json(step_dir / "summary.json", summary)
    return summary


def suite_step_passed(step: SuiteStep, result: RemoteExecutorDryRunResult) -> tuple[bool, str | None]:
    receipt = result.receipt
    if not result.prefixed_receipt_parsed:
        return False, "prefixed receipt was not parsed"
    if receipt.accepted != step.expect_accepted:
        return False, f"accepted={receipt.accepted}, expected={step.expect_accepted}"
    if receipt.executed:
        return False, "dry-run receipt reported executed=true"
    if not receipt.publish_disabled:
        return False, "dry-run receipt did not report publish_disabled=true"
    if receipt.ros_published:
        return False, "dry-run receipt reported ros_published=true"
    if step.expect_reason_contains:
        reason = receipt.rejected_reason or ""
        if step.expect_reason_contains not in reason:
            return False, f"rejected_reason={reason!r} did not contain {step.expect_reason_contains!r}"
    if step.expect_accepted and receipt.rejected_reason is not None:
        return False, f"accepted receipt had rejected_reason={receipt.rejected_reason!r}"
    return True, None


def _case_command(base_command: dict[str, Any], suffix: str, sequence_delta: int, **overrides: Any) -> dict[str, Any]:
    data = dict(base_command)
    base_sequence = int(data.get("sequence_id", 1))
    data["command_id"] = f"{data.get('command_id', 'vcmd')}_{suffix}"
    data["sequence_id"] = base_sequence + sequence_delta
    data.update(overrides)
    return data


def _safe_slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    main()

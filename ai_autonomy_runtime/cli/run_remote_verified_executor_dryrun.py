from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_autonomy_runtime.adapters.jackal.ssh_executor_dryrun_bridge import (
    RemoteExecutorDryRunConfig,
    run_remote_executor_dryrun,
)
from ai_autonomy_runtime.core.audit_logger import _to_jsonable


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Send a VerifiedCommand to the Jetson executor-equivalent dry-run over SSH."
    )
    parser.add_argument("--host", default="192.0.2.10")
    parser.add_argument("--user", default="robot")
    parser.add_argument("--remote-project-dir", default="/home/robot/ai-autonomy-ugv")
    parser.add_argument("--identity-file", default=_default_identity_file())
    parser.add_argument("--remote-config", default="configs/jackal_executor_safety.yaml")
    parser.add_argument("--remote-state-file", default=None)
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--executor-armed-preview", action="store_true")
    parser.add_argument(
        "--record-dryrun-state-preview",
        action="store_true",
        help="Record accepted dry-run sequence state on the Jetson for replay testing only.",
    )
    parser.add_argument(
        "--refresh-time-window-preview",
        action="store_true",
        help="Refresh the short VerifiedCommand TTL for remote dry-run transport only.",
    )
    parser.add_argument("--ssh-connect-timeout", type=int, default=30)
    parser.add_argument("--executor-timeout", type=int, default=30)
    parser.add_argument("--skip-code-sync", action="store_true")
    args = parser.parse_args()

    summary = run_remote_executor_dryrun_cli(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["accepted"]:
        raise SystemExit(2)


def run_remote_executor_dryrun_cli(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output or Path("local_outputs") / "remote_executor_dryrun" / _timestamp())
    output_dir.mkdir(parents=True, exist_ok=True)

    original_payload = Path(args.input_file).read_text(encoding="utf-8")

    code_sync: dict[str, Any] = {"enabled": not args.skip_code_sync, "ok": True, "error": None}
    if not args.skip_code_sync:
        code_sync = _sync_remote_dryrun_code(args)

    payload = original_payload
    if args.refresh_time_window_preview:
        _write_json(output_dir / "original_verified_command.json", json.loads(original_payload))

    _write_json(output_dir / "input_verified_command.json", json.loads(payload))

    config = RemoteExecutorDryRunConfig(
        host=args.host,
        user=args.user,
        remote_project_dir=args.remote_project_dir,
        identity_file=args.identity_file,
        executor_config=args.remote_config,
        state_file=args.remote_state_file,
        ssh_connect_timeout_s=args.ssh_connect_timeout,
        executor_timeout_s=args.executor_timeout,
    )
    result = run_remote_executor_dryrun(
        payload,
        config,
        executor_armed_preview=args.executor_armed_preview,
        refresh_time_window_preview=args.refresh_time_window_preview,
        record_dryrun_state_preview=args.record_dryrun_state_preview,
    )
    time_window_refresh = _time_window_refresh_from_events(result.events)

    receipt_payload = result.receipt.model_dump(mode="json")
    _write_json(output_dir / "remote_execution_receipt.json", receipt_payload)
    _write_jsonl(output_dir / "remote_executor_events.jsonl", result.events)
    (output_dir / "raw_ssh_stdout.log").write_text(result.raw_stdout, encoding="utf-8")
    (output_dir / "raw_ssh_stderr.log").write_text(result.raw_stderr, encoding="utf-8")

    summary = {
        "accepted": result.receipt.accepted,
        "executed": result.receipt.executed,
        "publish_disabled": result.receipt.publish_disabled,
        "ros_published": result.receipt.ros_published,
        "rejected_reason": result.receipt.rejected_reason,
        "output_dir": str(output_dir),
        "input_verified_command": str(output_dir / "input_verified_command.json"),
        "remote_execution_receipt": str(output_dir / "remote_execution_receipt.json"),
        "remote_executor_events": str(output_dir / "remote_executor_events.jsonl"),
        "raw_ssh_stdout": str(output_dir / "raw_ssh_stdout.log"),
        "raw_ssh_stderr": str(output_dir / "raw_ssh_stderr.log"),
        "remote_returncode": result.returncode,
        "remote_command": result.remote_command,
        "ssh_command": result.ssh_command,
        "prefixed_receipt_parsed": result.prefixed_receipt_parsed,
        "prefixed_event_count": len(result.events),
        "malformed_protocol_lines": result.malformed_protocol_lines,
        "executor_armed_preview": bool(args.executor_armed_preview),
        "record_dryrun_state_preview": bool(args.record_dryrun_state_preview),
        "code_sync": code_sync,
        "time_window_refreshed_for_preview": bool(args.refresh_time_window_preview),
        "time_window_refresh": time_window_refresh,
        "dry_run": True,
        "ssh_used": True,
        "llm_used": False,
        "manual_teleop_invoked": False,
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(_to_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(_to_jsonable(row), ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _time_window_refresh_from_events(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        refresh = event.get("time_window_refresh")
        if isinstance(refresh, dict):
            return refresh
    return None


def _sync_remote_dryrun_code(args: argparse.Namespace) -> dict[str, Any]:
    target = f"{args.user}@{args.host}"
    ssh_args = _ssh_args(args.identity_file, args.ssh_connect_timeout)
    scp_args = _scp_args(args.identity_file, args.ssh_connect_timeout)
    sources = [
        Path("ai_autonomy_runtime") / "schemas" / "__init__.py",
        Path("ai_autonomy_runtime") / "schemas" / "execution_receipt.py",
        Path("ai_autonomy_runtime") / "schemas" / "verified_command.py",
        Path("ai_autonomy_runtime") / "adapters" / "jackal" / "executor_safety.py",
        Path("ai_autonomy_runtime") / "adapters" / "jackal" / "executor_dryrun.py",
        Path("ai_autonomy_runtime") / "cli" / "run_verified_executor_dryrun.py",
    ]
    remote_config = Path(args.remote_config)
    if remote_config.exists():
        sources.append(remote_config)
    remote_dirs = sorted({str(Path(args.remote_project_dir) / source.parent).replace("\\", "/") for source in sources})
    try:
        mkdir_command = "mkdir -p " + " ".join(_quote_remote_path(path) for path in remote_dirs)
        subprocess.run(["ssh", *ssh_args, target, mkdir_command], check=True, capture_output=True, text=True)
        for source in sources:
            remote_dir = str(Path(args.remote_project_dir) / source.parent).replace("\\", "/")
            subprocess.run(
                ["scp", *scp_args, str(source), f"{target}:{remote_dir}/"],
                check=True,
                capture_output=True,
                text=True,
            )
    except subprocess.CalledProcessError as exc:
        return {
            "enabled": True,
            "ok": False,
            "error": exc.stderr.strip() or exc.stdout.strip() or str(exc),
            "files": [str(source) for source in sources],
        }
    return {"enabled": True, "ok": True, "error": None, "files": [str(source) for source in sources]}


def _ssh_args(identity_file: str | None, connect_timeout_s: int) -> list[str]:
    args = [
        "-o",
        f"ConnectTimeout={connect_timeout_s}",
        "-o",
        "ServerAliveInterval=10",
        "-o",
        "ServerAliveCountMax=3",
    ]
    if identity_file and _path_exists(identity_file):
        return ["-i", identity_file, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", *args]
    return args


def _scp_args(identity_file: str | None, connect_timeout_s: int) -> list[str]:
    return _ssh_args(identity_file, connect_timeout_s)


def _path_exists(path: str) -> bool:
    try:
        return Path(path).exists()
    except OSError:
        return False


def _quote_remote_path(path: str) -> str:
    path = path.replace("\\", "/")
    if path.startswith("~/"):
        return "~/" + _single_quote(path[2:])
    return _single_quote(path)


def _single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _default_identity_file() -> str | None:
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if not home:
        return None
    return str(Path(home) / ".ssh" / "id_ed25519_ugv")


if __name__ == "__main__":
    main()

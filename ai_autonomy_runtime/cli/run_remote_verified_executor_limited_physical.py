from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_autonomy_runtime.core.audit_logger import _to_jsonable
from ai_autonomy_runtime.schemas.execution_receipt import ExecutionReceipt
from ai_autonomy_runtime.schemas.verified_command import current_time_ms


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a readiness-gated limited physical VerifiedCommand over SSH.")
    parser.add_argument("--host", default="192.0.2.10")
    parser.add_argument("--user", default="robot")
    parser.add_argument("--remote-project-dir", default="/home/robot/ai-autonomy-ugv")
    parser.add_argument("--identity-file", default=_default_identity_file())
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--readiness-report", required=True)
    parser.add_argument("--remote-config", default="configs/jackal_inverted_bench_executor.yaml")
    parser.add_argument("--remote-state-file", default="/tmp/ai_autonomy_inverted_bench_executor_state.json")
    parser.add_argument("--remote-readiness-path", default=None)
    parser.add_argument("--output", default=None)
    parser.add_argument("--ssh-connect-timeout", type=int, default=30)
    parser.add_argument("--executor-timeout", type=int, default=30)
    parser.add_argument("--skip-code-sync", action="store_true")
    parser.add_argument("--inverted-bench-confirmed", action="store_true")
    parser.add_argument("--i-understand-this-will-publish-cmd-vel", action="store_true")
    args = parser.parse_args()

    summary = run_remote_limited_physical(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["accepted"] or not summary["executed"]:
        raise SystemExit(2)


def run_remote_limited_physical(args: argparse.Namespace) -> dict[str, Any]:
    output_dir = Path(args.output or Path("local_outputs") / "limited_physical_executor" / _timestamp())
    output_dir.mkdir(parents=True, exist_ok=True)
    command_payload = Path(args.input_file).read_text(encoding="utf-8")
    readiness_payload = Path(args.readiness_report).read_text(encoding="utf-8")
    _write_json(output_dir / "input_verified_command.json", json.loads(command_payload))
    _write_json(output_dir / "readiness_review.json", json.loads(readiness_payload))

    local_block = _local_block_reason(args)
    if local_block:
        receipt = _failure_receipt(_raw_command_id(command_payload), local_block)
        return _write_summary(output_dir, args, receipt, "", "", None, "", [], False, local_block)

    code_sync = {"enabled": not args.skip_code_sync, "ok": True, "error": None}
    if not args.skip_code_sync:
        code_sync = _sync_remote_executor_code(args)
        if not code_sync.get("ok", False):
            receipt = _failure_receipt(_raw_command_id(command_payload), f"code_sync_failed: {code_sync.get('error')}")
            return _write_summary(output_dir, args, receipt, "", "", None, "", [], False, receipt.rejected_reason, code_sync)

    remote_readiness_path = args.remote_readiness_path or f"/tmp/ai_autonomy_readiness_{_timestamp()}.json"
    upload = _upload_readiness_report(args, remote_readiness_path)
    if upload:
        receipt = _failure_receipt(_raw_command_id(command_payload), upload)
        return _write_summary(output_dir, args, receipt, "", "", None, "", [], False, upload, code_sync)

    remote_command = build_remote_limited_physical_command(args, remote_readiness_path)
    ssh_command = ["ssh", *_ssh_args(args.identity_file, args.ssh_connect_timeout), f"{args.user}@{args.host}", remote_command]
    try:
        process = subprocess.run(
            ssh_command,
            input=command_payload,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=args.executor_timeout,
            check=False,
        )
        receipt, parsed = parse_executor_receipt_stdout(process.stdout, _raw_command_id(command_payload))
        return _write_summary(
            output_dir,
            args,
            receipt,
            process.stdout,
            process.stderr,
            process.returncode,
            remote_command,
            ssh_command,
            parsed,
            receipt.rejected_reason,
            code_sync,
            remote_readiness_path,
        )
    except subprocess.TimeoutExpired as exc:
        receipt = _failure_receipt(_raw_command_id(command_payload), f"limited_physical_executor_timeout: {exc}")
        return _write_summary(
            output_dir,
            args,
            receipt,
            exc.stdout or "",
            exc.stderr or "",
            None,
            remote_command,
            ssh_command,
            False,
            receipt.rejected_reason,
            code_sync,
            remote_readiness_path,
        )


def build_remote_limited_physical_command(args: argparse.Namespace, remote_readiness_path: str) -> str:
    inner_command = " && ".join(
        [
            f"cd {_quote_remote_path(args.remote_project_dir)}",
            "(deactivate 2>/dev/null || true)",
            "source /opt/ros/noetic/setup.bash",
            f"export ROS_MASTER_URI={shlex.quote(f'http://{args.host}:11311')}",
            f"export ROS_IP={shlex.quote(args.host)}",
            "export PYTHONPATH=$PWD:${PYTHONPATH:-}",
            " ".join(
                [
                    "python3",
                    "-m",
                    "ai_autonomy_runtime.cli.run_verified_executor",
                    "--config",
                    shlex.quote(_remote_path_text(args.remote_config)),
                    "--state-file",
                    shlex.quote(_remote_path_text(args.remote_state_file)),
                    "--input-json",
                    "-",
                    "--armed",
                    "--readiness-report",
                    shlex.quote(_remote_path_text(remote_readiness_path)),
                ]
            ),
        ]
    )
    return f"bash -lc {shlex.quote(inner_command)}"


def parse_executor_receipt_stdout(stdout: str, fallback_command_id: str) -> tuple[ExecutionReceipt, bool]:
    for raw_line in reversed(stdout.splitlines()):
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            try:
                return ExecutionReceipt.model_validate(payload), True
            except ValueError:
                continue
    return _failure_receipt(fallback_command_id, "limited_physical_executor_receipt_parse_failed"), False


def _local_block_reason(args: argparse.Namespace) -> str | None:
    if not args.inverted_bench_confirmed:
        return "inverted_bench_confirmation_required"
    if not args.i_understand_this_will_publish_cmd_vel:
        return "explicit_cmd_vel_publish_ack_required"
    return None


def _sync_remote_executor_code(args: argparse.Namespace) -> dict[str, Any]:
    target = f"{args.user}@{args.host}"
    ssh_args = _ssh_args(args.identity_file, args.ssh_connect_timeout)
    scp_args = _scp_args(args.identity_file, args.ssh_connect_timeout)
    sources = [
        Path("ai_autonomy_runtime") / "schemas" / "__init__.py",
        Path("ai_autonomy_runtime") / "schemas" / "execution_receipt.py",
        Path("ai_autonomy_runtime") / "schemas" / "verified_command.py",
        Path("ai_autonomy_runtime") / "adapters" / "jackal" / "executor_safety.py",
        Path("ai_autonomy_runtime") / "adapters" / "jackal" / "physical_readiness.py",
        Path("ai_autonomy_runtime") / "adapters" / "jackal" / "verified_executor.py",
        Path("ai_autonomy_runtime") / "cli" / "run_verified_executor.py",
        Path("configs") / "jackal_inverted_bench_executor.yaml",
    ]
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


def _upload_readiness_report(args: argparse.Namespace, remote_readiness_path: str) -> str | None:
    target = f"{args.user}@{args.host}"
    scp_args = _scp_args(args.identity_file, args.ssh_connect_timeout)
    try:
        subprocess.run(
            ["scp", *scp_args, args.readiness_report, f"{target}:{remote_readiness_path}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        return f"readiness_report_upload_failed: {exc.stderr.strip() or exc.stdout.strip() or exc}"
    return None


def _write_summary(
    output_dir: Path,
    args: argparse.Namespace,
    receipt: ExecutionReceipt,
    stdout: str,
    stderr: str,
    returncode: int | None,
    remote_command: str,
    ssh_command: list[str],
    receipt_parsed: bool,
    rejected_reason: str | None,
    code_sync: dict[str, Any] | None = None,
    remote_readiness_path: str | None = None,
) -> dict[str, Any]:
    _write_json(output_dir / "remote_execution_receipt.json", receipt.model_dump(mode="json"))
    (output_dir / "raw_ssh_stdout.log").write_text(stdout, encoding="utf-8")
    (output_dir / "raw_ssh_stderr.log").write_text(stderr, encoding="utf-8")
    summary = {
        "accepted": receipt.accepted,
        "executed": receipt.executed,
        "publish_disabled": receipt.publish_disabled,
        "ros_published": receipt.ros_published,
        "rejected_reason": rejected_reason,
        "output_dir": str(output_dir),
        "remote_execution_receipt": str(output_dir / "remote_execution_receipt.json"),
        "raw_ssh_stdout": str(output_dir / "raw_ssh_stdout.log"),
        "raw_ssh_stderr": str(output_dir / "raw_ssh_stderr.log"),
        "receipt_parsed": receipt_parsed,
        "remote_returncode": returncode,
        "remote_command": remote_command,
        "ssh_command": ssh_command,
        "code_sync": code_sync or {"enabled": False, "ok": True, "error": None},
        "remote_readiness_path": remote_readiness_path,
        "inverted_bench_confirmed": bool(args.inverted_bench_confirmed),
        "explicit_cmd_vel_publish_ack": bool(args.i_understand_this_will_publish_cmd_vel),
        "ssh_used": bool(remote_command),
        "llm_used": False,
        "manual_teleop_invoked": False,
    }
    _write_json(output_dir / "summary.json", summary)
    return summary


def _failure_receipt(command_id: str, reason: str) -> ExecutionReceipt:
    now_ms = current_time_ms()
    return ExecutionReceipt(
        command_id=command_id,
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


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(_to_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _ssh_args(identity_file: str | None, connect_timeout_s: int) -> list[str]:
    args = ["-o", f"ConnectTimeout={connect_timeout_s}", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=3"]
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
    path = _remote_path_text(path)
    if path.startswith("~/"):
        return "~/" + shlex.quote(path[2:])
    return shlex.quote(path)


def _remote_path_text(path: str) -> str:
    return path.replace("\\", "/")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _default_identity_file() -> str | None:
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if not home:
        return None
    return str(Path(home) / ".ssh" / "id_ed25519_ugv")


if __name__ == "__main__":
    main()

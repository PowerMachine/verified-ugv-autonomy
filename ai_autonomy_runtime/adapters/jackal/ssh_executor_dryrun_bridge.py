from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_autonomy_runtime.schemas.execution_receipt import ExecutionReceipt
from ai_autonomy_runtime.schemas.verified_command import current_time_ms


EXECUTOR_RECEIPT_PREFIX = "UGV_EXECUTOR_RECEIPT_JSON "
EXECUTOR_EVENT_PREFIX = "UGV_EXECUTOR_EVENT_JSON "


class RemoteExecutorDryRunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "192.0.2.10"
    user: str = "robot"
    remote_project_dir: str = "/home/robot/ai-autonomy-ugv"
    identity_file: str | None = None
    ros_master_uri: str | None = None
    ros_ip: str | None = None
    python_executable: str = "python3"
    executor_config: str = "configs/jackal_executor_safety.yaml"
    state_file: str | None = None
    ssh_connect_timeout_s: int = Field(default=30, gt=0)
    executor_timeout_s: int = Field(default=30, gt=0)


class ParsedExecutorDryRunOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt: ExecutionReceipt | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    malformed: list[dict[str, str]] = Field(default_factory=list)


class RemoteExecutorDryRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt: ExecutionReceipt
    events: list[dict[str, Any]] = Field(default_factory=list)
    raw_stdout: str = ""
    raw_stderr: str = ""
    returncode: int | None = None
    remote_command: str
    ssh_command: list[str]
    prefixed_receipt_parsed: bool = False
    malformed_protocol_lines: list[dict[str, str]] = Field(default_factory=list)


def run_remote_executor_dryrun(
    payload: str,
    config: RemoteExecutorDryRunConfig,
    *,
    executor_armed_preview: bool = False,
    refresh_time_window_preview: bool = False,
    record_dryrun_state_preview: bool = False,
) -> RemoteExecutorDryRunResult:
    remote_command = build_remote_executor_dryrun_command(
        config,
        executor_armed_preview=executor_armed_preview,
        refresh_time_window_preview=refresh_time_window_preview,
        record_dryrun_state_preview=record_dryrun_state_preview,
    )
    ssh_command = build_ssh_executor_dryrun_command(config, remote_command)
    started_at_ms = current_time_ms()
    try:
        process = subprocess.run(
            ssh_command,
            input=payload,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=config.executor_timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        receipt = _failure_receipt(
            _raw_command_id(payload),
            f"ssh_executor_dryrun_timeout: {exc}",
            started_at_ms,
        )
        return RemoteExecutorDryRunResult(
            receipt=receipt,
            raw_stdout=exc.stdout or "",
            raw_stderr=exc.stderr or "",
            returncode=None,
            remote_command=remote_command,
            ssh_command=ssh_command,
            prefixed_receipt_parsed=False,
        )
    except OSError as exc:
        receipt = _failure_receipt(
            _raw_command_id(payload),
            f"ssh_executor_dryrun_unavailable: {exc}",
            started_at_ms,
        )
        return RemoteExecutorDryRunResult(
            receipt=receipt,
            raw_stdout="",
            raw_stderr=str(exc),
            returncode=None,
            remote_command=remote_command,
            ssh_command=ssh_command,
            prefixed_receipt_parsed=False,
        )

    parsed = parse_executor_dryrun_protocol(process.stdout)
    receipt = parsed.receipt
    prefixed_receipt_parsed = receipt is not None
    if receipt is None:
        detail = process.stderr.strip() or process.stdout.strip() or "no prefixed receipt in SSH output"
        receipt = _failure_receipt(
            _raw_command_id(payload),
            f"ssh_executor_dryrun_parse_failed: {detail[-500:]}",
            started_at_ms,
        )

    return RemoteExecutorDryRunResult(
        receipt=receipt,
        events=parsed.events,
        raw_stdout=process.stdout,
        raw_stderr=process.stderr,
        returncode=process.returncode,
        remote_command=remote_command,
        ssh_command=ssh_command,
        prefixed_receipt_parsed=prefixed_receipt_parsed,
        malformed_protocol_lines=parsed.malformed,
    )


def build_ssh_executor_dryrun_command(
    config: RemoteExecutorDryRunConfig,
    remote_command: str,
) -> list[str]:
    target = f"{config.user}@{config.host}"
    return ["ssh", *_ssh_args(config), target, remote_command]


def build_remote_executor_dryrun_command(
    config: RemoteExecutorDryRunConfig,
    *,
    executor_armed_preview: bool = False,
    refresh_time_window_preview: bool = False,
    record_dryrun_state_preview: bool = False,
) -> str:
    ros_master_uri = config.ros_master_uri or f"http://{config.host}:11311"
    ros_ip = config.ros_ip or config.host
    cli_args = [
        shlex.quote(config.python_executable),
        "-m",
        "ai_autonomy_runtime.cli.run_verified_executor_dryrun",
        "--config",
        shlex.quote(_remote_path_text(config.executor_config)),
        "--input-json",
        "-",
        "--emit-prefixed-receipt",
    ]
    if config.state_file:
        cli_args.extend(["--state-file", shlex.quote(_remote_path_text(config.state_file))])
    if executor_armed_preview:
        cli_args.append("--executor-armed-preview")
    if refresh_time_window_preview:
        cli_args.append("--refresh-time-window-preview")
    if record_dryrun_state_preview:
        cli_args.append("--record-dryrun-state-preview")

    inner_command = " && ".join(
        [
            f"cd {_quote_remote_path(config.remote_project_dir)}",
            "(deactivate 2>/dev/null || true)",
            "source /opt/ros/noetic/setup.bash",
            f"export ROS_MASTER_URI={shlex.quote(ros_master_uri)}",
            f"export ROS_IP={shlex.quote(ros_ip)}",
            "export PYTHONPATH=$PWD:${PYTHONPATH:-}",
            " ".join(cli_args),
        ]
    )
    return f"bash -lc {shlex.quote(inner_command)}"


def parse_executor_dryrun_protocol(stdout: str) -> ParsedExecutorDryRunOutput:
    receipt: ExecutionReceipt | None = None
    events: list[dict[str, Any]] = []
    malformed: list[dict[str, str]] = []
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if line.startswith(EXECUTOR_EVENT_PREFIX):
            payload = line.removeprefix(EXECUTOR_EVENT_PREFIX)
            parsed, error = _parse_prefixed_json(payload)
            if isinstance(parsed, dict):
                events.append(parsed)
            else:
                malformed.append({"line": raw_line, "error": error or "event payload is not an object"})
        elif line.startswith(EXECUTOR_RECEIPT_PREFIX):
            payload = line.removeprefix(EXECUTOR_RECEIPT_PREFIX)
            parsed, error = _parse_prefixed_json(payload)
            if isinstance(parsed, dict):
                try:
                    receipt = ExecutionReceipt.model_validate(parsed)
                except ValueError as exc:
                    malformed.append({"line": raw_line, "error": str(exc)})
            else:
                malformed.append({"line": raw_line, "error": error or "receipt payload is not an object"})
    return ParsedExecutorDryRunOutput(receipt=receipt, events=events, malformed=malformed)


def _parse_prefixed_json(payload: str) -> tuple[Any | None, str | None]:
    try:
        return json.loads(payload), None
    except json.JSONDecodeError as exc:
        return None, str(exc)


def _failure_receipt(command_id: str, reason: str, started_at_ms: int) -> ExecutionReceipt:
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
        started_at_ms=started_at_ms,
        finished_at_ms=current_time_ms(),
    )


def _raw_command_id(payload: str) -> str:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return "unknown"
    value = data.get("command_id") if isinstance(data, dict) else None
    return str(value) if value is not None else "unknown"


def _ssh_args(config: RemoteExecutorDryRunConfig) -> list[str]:
    args = [
        "-o",
        f"ConnectTimeout={config.ssh_connect_timeout_s}",
        "-o",
        "ServerAliveInterval=10",
        "-o",
        "ServerAliveCountMax=3",
    ]
    identity_file = config.identity_file or _default_identity_file()
    if identity_file and _path_exists(identity_file):
        return ["-i", identity_file, "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", *args]
    return args


def _path_exists(path: str) -> bool:
    try:
        return Path(path).exists()
    except OSError:
        return False


def _default_identity_file() -> str | None:
    home = os.environ.get("USERPROFILE") or os.environ.get("HOME")
    if not home:
        return None
    return str(Path(home) / ".ssh" / "id_ed25519_ugv")


def _quote_remote_path(path: str) -> str:
    path = _remote_path_text(path)
    if path.startswith("~/"):
        return "~/" + shlex.quote(path[2:])
    return shlex.quote(path)


def _remote_path_text(path: str) -> str:
    return path.replace("\\", "/")

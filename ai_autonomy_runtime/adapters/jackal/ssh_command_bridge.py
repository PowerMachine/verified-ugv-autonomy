from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_autonomy_runtime.core.config import load_yaml
from ai_autonomy_runtime.schemas.execution_receipt import ExecutionReceipt
from ai_autonomy_runtime.schemas.verified_command import VerifiedCommand, current_time_ms


class BridgeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "192.0.2.10"
    user: str = "robot"
    project_dir: str = "~/ai-autonomy-ugv"
    ros_master_uri: str = "http://192.0.2.10:11311"
    ros_ip: str = "192.0.2.10"
    python_executable: str = "python3"
    executor_config: str = "configs/jackal_executor_safety.yaml"
    ssh_connect_timeout_s: int = Field(default=10, gt=0)
    executor_timeout_s: int = Field(default=15, gt=0)
    default_target_robot: str = "jackal"
    default_dry_run: bool = True

    @classmethod
    def from_yaml(cls, path: str | Path) -> "BridgeConfig":
        return cls.model_validate(load_yaml(path))


class SshCommandBridge:
    def __init__(self, config: BridgeConfig) -> None:
        self.config = config

    def run(self, command: VerifiedCommand, armed: bool) -> ExecutionReceipt:
        remote_command = build_remote_executor_command(self.config, armed=armed)
        started_at_ms = current_time_ms()
        try:
            process = subprocess.run(
                [
                    "ssh",
                    "-o",
                    f"ConnectTimeout={self.config.ssh_connect_timeout_s}",
                    f"{self.config.user}@{self.config.host}",
                    remote_command,
                ],
                input=command.model_dump_json(),
                text=True,
                capture_output=True,
                timeout=self.config.executor_timeout_s,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return _bridge_failure(command.command_id, f"ssh_executor_unavailable: {exc}", started_at_ms)
        if process.returncode != 0:
            return _bridge_failure(
                command.command_id,
                f"ssh_executor_failed: {process.stderr.strip() or process.stdout.strip()}",
                started_at_ms,
            )
        return parse_execution_receipt(process.stdout, command.command_id)


def build_remote_executor_command(config: BridgeConfig, armed: bool) -> str:
    args = [
        shlex.quote(config.python_executable),
        "-m",
        "ai_autonomy_runtime.cli.run_verified_executor",
        "--config",
        shlex.quote(config.executor_config),
        "--input-json",
        "-",
    ]
    if armed:
        args.append("--armed")
    return " && ".join(
        [
            f"cd {_quote_remote_path(config.project_dir)}",
            "source /opt/ros/noetic/setup.bash",
            f"export ROS_MASTER_URI={shlex.quote(config.ros_master_uri)}",
            f"export ROS_IP={shlex.quote(config.ros_ip)}",
            "export PYTHONPATH=$PWD:${PYTHONPATH:-}",
            " ".join(args),
        ]
    )


def parse_execution_receipt(stdout: str, fallback_command_id: str) -> ExecutionReceipt:
    text = stdout.strip()
    if not text:
        return _bridge_parse_failure(fallback_command_id, "empty stdout from executor")
    candidates = [text, *reversed(text.splitlines())]
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            try:
                return ExecutionReceipt.model_validate(data)
            except ValueError:
                continue
    return _bridge_parse_failure(fallback_command_id, f"could not parse executor receipt: {text[-300:]}")


def _bridge_parse_failure(command_id: str, reason: str) -> ExecutionReceipt:
    now_ms = current_time_ms()
    return _bridge_failure(command_id, reason, now_ms)


def _bridge_failure(command_id: str, reason: str, started_at_ms: int) -> ExecutionReceipt:
    finished_at_ms = current_time_ms()
    return ExecutionReceipt(
        command_id=command_id,
        accepted=False,
        executed=False,
        rejected_reason=reason,
        publish_topic=None,
        publish_count=0,
        stop_published=False,
        executor_latency_ms=0.0,
        cmd_vel_out_observed=None,
        odom_observed=None,
        started_at_ms=started_at_ms,
        finished_at_ms=finished_at_ms,
    )


def _quote_remote_path(path: str) -> str:
    if path.startswith("~/"):
        return "~/" + shlex.quote(path[2:])
    return shlex.quote(path)

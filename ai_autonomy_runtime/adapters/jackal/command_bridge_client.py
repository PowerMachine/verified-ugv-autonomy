from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from ai_autonomy_runtime.adapters.jackal.executor_safety import ExecutorSafetyConfig
from ai_autonomy_runtime.adapters.jackal.ssh_command_bridge import BridgeConfig, SshCommandBridge
from ai_autonomy_runtime.core.audit_logger import _to_jsonable, create_run_dir
from ai_autonomy_runtime.schemas.execution_receipt import ExecutionReceipt
from ai_autonomy_runtime.schemas.operator_approval import OperatorApproval
from ai_autonomy_runtime.schemas.verified_command import VerifiedCommand, current_time_ms


BridgeCommand = Literal["forward", "back", "left", "right", "stop"]


class CommandBridgeClient:
    def __init__(
        self,
        bridge_config: BridgeConfig,
        safety_config: ExecutorSafetyConfig,
        runs_dir: str | Path = "runs",
        run_dir: str | Path | None = None,
    ) -> None:
        self.bridge_config = bridge_config
        self.safety_config = safety_config
        self.run_dir = Path(run_dir) if run_dir is not None else create_run_dir(runs_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def build_manual_command(
        self,
        command: BridgeCommand,
        duration_ms: int,
        linear: float,
        angular: float,
        armed: bool,
        sequence_id: int | None = None,
    ) -> VerifiedCommand:
        created_at_ms = current_time_ms()
        approval = (
            OperatorApproval(
                approved=True,
                approved_at_ms=created_at_ms,
                expires_at_ms=created_at_ms + self.safety_config.command_ttl_ms,
                scope={"command": command, "target_robot": self.bridge_config.default_target_robot},
                notes="manual bridge smoke-test approval",
            )
            if armed
            else None
        )
        linear_x, angular_z = command_to_velocity(command, linear, angular)
        return VerifiedCommand(
            sequence_id=sequence_id if sequence_id is not None else created_at_ms,
            created_at_ms=created_at_ms,
            expires_at_ms=created_at_ms + self.safety_config.command_ttl_ms,
            target_robot=self.bridge_config.default_target_robot,
            target_topic=self.safety_config.allowed_topic,
            command_type="velocity_primitive",
            linear_x=linear_x,
            angular_z=angular_z,
            duration_ms=duration_ms,
            max_linear_x=self.safety_config.max_linear_x,
            max_angular_z=self.safety_config.max_angular_z,
            requires_stop_after=True,
            operator_armed=armed,
            approval_id=approval.approval_id if approval else None,
            verifier_summary={
                "source": "manual_bridge_smoke_test",
                "approval": approval.model_dump(mode="json") if approval else None,
                "safety_config": {
                    "max_linear_x": self.safety_config.max_linear_x,
                    "max_angular_z": self.safety_config.max_angular_z,
                    "max_duration_ms": self.safety_config.max_duration_ms,
                    "command_ttl_ms": self.safety_config.command_ttl_ms,
                },
            },
        )

    def run(self, command: VerifiedCommand, armed: bool, dry_run: bool) -> ExecutionReceipt:
        self._append_jsonl("verified_commands.jsonl", command)
        if dry_run:
            receipt = self._dry_run_receipt(command)
        else:
            receipt = SshCommandBridge(self.bridge_config).run(command, armed=armed)
        self._append_jsonl("execution_receipts.jsonl", receipt)
        return receipt

    def _dry_run_receipt(self, command: VerifiedCommand) -> ExecutionReceipt:
        now_ms = current_time_ms()
        return ExecutionReceipt(
            command_id=command.command_id,
            accepted=True,
            executed=False,
            rejected_reason="dry_run_no_ssh",
            publish_topic=None,
            publish_count=0,
            stop_published=False,
            executor_latency_ms=0.0,
            cmd_vel_out_observed=None,
            odom_observed=None,
            started_at_ms=now_ms,
            finished_at_ms=now_ms,
        )

    def _append_jsonl(self, filename: str, payload: Any) -> None:
        path = self.run_dir / filename
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_to_jsonable(payload), ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def command_to_velocity(command: BridgeCommand, linear: float, angular: float) -> tuple[float, float]:
    linear_mag = abs(linear)
    angular_mag = abs(angular)
    if command == "forward":
        return linear_mag, 0.0
    if command == "back":
        return -linear_mag, 0.0
    if command == "left":
        return 0.0, angular_mag
    if command == "right":
        return 0.0, -angular_mag
    return 0.0, 0.0

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ai_autonomy_runtime.adapters.jackal.executor_safety import (
    DEFAULT_EXECUTOR_STATE,
    ExecutorSafetyConfig,
    SafetyCheck,
    evaluate_verified_command,
    last_sequence_for_command,
    load_executor_state,
    save_executor_state,
)
from ai_autonomy_runtime.core.audit_logger import _to_jsonable, create_run_dir
from ai_autonomy_runtime.schemas.execution_receipt import ExecutionReceipt
from ai_autonomy_runtime.schemas.verified_command import VerifiedCommand, current_time_ms


class VerifiedExecutor:
    """Jetson-side final gate for VerifiedCommand execution."""

    def __init__(
        self,
        config: ExecutorSafetyConfig | None = None,
        config_path: str | Path | None = None,
        state_path: str | Path = DEFAULT_EXECUTOR_STATE,
        runs_dir: str | Path = "runs",
        run_dir: str | Path | None = None,
    ) -> None:
        if config is not None:
            self.config = config
        elif config_path is not None:
            self.config = ExecutorSafetyConfig.from_yaml(config_path)
        else:
            self.config = ExecutorSafetyConfig.from_yaml()
        self.state_path = Path(state_path)
        self.run_dir = Path(run_dir) if run_dir is not None else create_run_dir(runs_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    def execute(self, payload: str | bytes | dict[str, Any] | VerifiedCommand, armed: bool = False) -> ExecutionReceipt:
        started_at_ms = current_time_ms()
        start_perf = time.perf_counter()

        command, schema_error = self._parse_command(payload)
        if command is None:
            receipt = self._receipt(
                command_id=_raw_field(payload, "command_id") or "unknown",
                accepted=False,
                executed=False,
                rejected_reason=f"schema_validation_failed: {schema_error}",
                publish_topic=None,
                publish_count=0,
                stop_published=False,
                started_at_ms=started_at_ms,
                start_perf=start_perf,
            )
            self._append_jsonl("verified_commands.jsonl", {"raw": _json_raw(payload), "schema_error": schema_error})
            self._append_jsonl(
                "safety_checks.jsonl",
                SafetyCheck(
                    command_id=receipt.command_id,
                    sequence_id=_raw_int(payload, "sequence_id"),
                    check="schema_validation",
                    passed=False,
                    detail=str(schema_error),
                ),
            )
            self._append_jsonl("execution_receipts.jsonl", receipt)
            return receipt

        self._append_jsonl("verified_commands.jsonl", command)

        state = load_executor_state(self.state_path)
        last_sequence_id = last_sequence_for_command(state, command)
        evaluation = evaluate_verified_command(
            command,
            self.config,
            last_sequence_id=last_sequence_id,
            executor_armed=armed,
        )
        for check in evaluation.checks:
            self._append_jsonl("safety_checks.jsonl", check)

        if not evaluation.accepted:
            receipt = self._receipt(
                command_id=command.command_id,
                accepted=False,
                executed=False,
                rejected_reason=evaluation.rejected_reason,
                publish_topic=None,
                publish_count=0,
                stop_published=False,
                started_at_ms=started_at_ms,
                start_perf=start_perf,
            )
            self._append_jsonl("execution_receipts.jsonl", receipt)
            return receipt

        try:
            save_executor_state(self.state_path, command)
        except Exception as exc:
            receipt = self._receipt(
                command_id=command.command_id,
                accepted=False,
                executed=False,
                rejected_reason=f"state_persist_failed: {exc}",
                publish_topic=None,
                publish_count=0,
                stop_published=False,
                started_at_ms=started_at_ms,
                start_perf=start_perf,
            )
            self._append_jsonl("execution_receipts.jsonl", receipt)
            return receipt

        publish_count = 0
        stop_published = False
        try:
            publish_count, stop_published = self._publish_ros(command)
        except Exception as exc:  # pragma: no cover - exercised on Jetson with ROS.
            receipt = self._receipt(
                command_id=command.command_id,
                accepted=True,
                executed=False,
                rejected_reason=f"execution_error: {exc}",
                publish_topic=command.target_topic,
                publish_count=publish_count,
                stop_published=stop_published,
                started_at_ms=started_at_ms,
                start_perf=start_perf,
            )
            self._append_jsonl("execution_receipts.jsonl", receipt)
            return receipt

        receipt = self._receipt(
            command_id=command.command_id,
            accepted=True,
            executed=True,
            rejected_reason=None,
            publish_topic=command.target_topic,
            publish_count=publish_count,
            stop_published=stop_published,
            started_at_ms=started_at_ms,
            start_perf=start_perf,
        )
        self._append_jsonl("execution_receipts.jsonl", receipt)
        return receipt

    def _parse_command(self, payload: str | bytes | dict[str, Any] | VerifiedCommand) -> tuple[VerifiedCommand | None, str | None]:
        try:
            if isinstance(payload, VerifiedCommand):
                return payload, None
            if isinstance(payload, bytes):
                return VerifiedCommand.model_validate_json(payload.decode("utf-8")), None
            if isinstance(payload, str):
                return VerifiedCommand.model_validate_json(payload), None
            return VerifiedCommand.model_validate(payload), None
        except (ValidationError, ValueError) as exc:
            return None, str(exc)

    def _publish_ros(self, command: VerifiedCommand) -> tuple[int, bool]:  # pragma: no cover - requires ROS.
        try:
            import rospy
            from geometry_msgs.msg import Twist
        except ImportError as exc:
            raise RuntimeError("ROS1 Python modules unavailable; source /opt/ros/noetic/setup.bash") from exc

        rospy.init_node("ai_autonomy_verified_executor", anonymous=True, disable_signals=True)
        publisher = rospy.Publisher(command.target_topic, Twist, queue_size=1)
        time.sleep(0.1)

        publish_count = 0
        stop_published = False
        try:
            rate = rospy.Rate(self.config.publish_rate_hz)
            deadline = time.time() + command.duration_ms / 1000.0
            while not rospy.is_shutdown() and time.time() < deadline:
                message = Twist()
                message.linear.x = command.linear_x
                message.angular.z = command.angular_z
                publisher.publish(message)
                publish_count += 1
                rate.sleep()
        finally:
            stop_published = self._publish_stop(rospy, publisher, Twist)
        return publish_count, stop_published

    def _publish_stop(self, rospy: Any, publisher: Any, Twist: Any) -> bool:  # pragma: no cover - requires ROS.
        rate = rospy.Rate(self.config.publish_rate_hz)
        for _ in range(self.config.stop_publish_count):
            if rospy.is_shutdown():
                return False
            message = Twist()
            message.linear.x = 0.0
            message.angular.z = 0.0
            publisher.publish(message)
            rate.sleep()
        return True

    def _receipt(
        self,
        command_id: str,
        accepted: bool,
        executed: bool,
        rejected_reason: str | None,
        publish_topic: str | None,
        publish_count: int,
        stop_published: bool,
        started_at_ms: int,
        start_perf: float,
    ) -> ExecutionReceipt:
        finished_at_ms = current_time_ms()
        return ExecutionReceipt(
            command_id=command_id,
            accepted=accepted,
            executed=executed,
            publish_disabled=False,
            ros_published=bool(executed and publish_count > 0),
            rejected_reason=rejected_reason,
            publish_topic=publish_topic,
            publish_count=publish_count,
            stop_published=stop_published,
            executor_latency_ms=(time.perf_counter() - start_perf) * 1000.0,
            cmd_vel_out_observed=None,
            odom_observed=None,
            started_at_ms=started_at_ms,
            finished_at_ms=finished_at_ms,
        )

    def _append_jsonl(self, filename: str, payload: Any) -> None:
        path = self.run_dir / filename
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_to_jsonable(payload), ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _raw_field(payload: Any, field: str) -> str | None:
    if isinstance(payload, dict):
        value = payload.get(field)
        return str(value) if value is not None else None
    try:
        data = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else str(payload))
    except json.JSONDecodeError:
        return None
    value = data.get(field) if isinstance(data, dict) else None
    return str(value) if value is not None else None


def _raw_int(payload: Any, field: str) -> int | None:
    value = _raw_field(payload, field)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _json_raw(payload: Any) -> Any:
    if isinstance(payload, (dict, list)):
        return payload
    if isinstance(payload, VerifiedCommand):
        return payload.model_dump(mode="json")
    try:
        return json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else str(payload))
    except json.JSONDecodeError:
        return str(payload)

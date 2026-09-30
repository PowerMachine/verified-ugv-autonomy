from __future__ import annotations

import json
from pathlib import Path
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_autonomy_runtime.core.config import load_yaml
from ai_autonomy_runtime.schemas.verified_command import VerifiedCommand, current_time_ms


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXECUTOR_CONFIG = PROJECT_ROOT / "configs" / "jackal_executor_safety.yaml"
DEFAULT_EXECUTOR_STATE = PROJECT_ROOT / "runs" / "executor_state.json"


class ExecutorSafetyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_topic: str = "/cmd_vel"
    max_linear_x: float = Field(default=0.08, gt=0)
    max_angular_z: float = Field(default=0.15, gt=0)
    max_duration_ms: int = Field(default=1000, gt=0)
    command_ttl_ms: int = Field(default=800, gt=0)
    publish_rate_hz: float = Field(default=10.0, gt=0)
    stop_publish_count: int = Field(default=5, ge=1)
    require_operator_armed: bool = True

    @classmethod
    def from_yaml(cls, path: str | Path = DEFAULT_EXECUTOR_CONFIG) -> "ExecutorSafetyConfig":
        return cls.model_validate(load_yaml(path))


class SafetyCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str
    sequence_id: Optional[int] = None
    check: str
    passed: bool
    detail: str = ""
    checked_at_ms: int = Field(default_factory=current_time_ms, ge=0)


class SafetyEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    rejected_reason: Optional[str] = None
    checks: List[SafetyCheck] = Field(default_factory=list)


def load_executor_state(path: str | Path = DEFAULT_EXECUTOR_STATE) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.exists():
        return {}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_executor_state(path: str | Path, command: VerifiedCommand) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = load_executor_state(state_path)
    state["last_sequence_id"] = command.sequence_id
    state.setdefault("last_sequence_by_robot", {})
    state["last_sequence_by_robot"][command.target_robot] = command.sequence_id
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def last_sequence_for_command(state: dict[str, Any], command: VerifiedCommand) -> int | None:
    by_robot = state.get("last_sequence_by_robot")
    if isinstance(by_robot, dict) and command.target_robot in by_robot:
        return _try_int(by_robot[command.target_robot])
    return _try_int(state.get("last_sequence_id"))


def evaluate_verified_command(
    command: VerifiedCommand,
    config: ExecutorSafetyConfig,
    last_sequence_id: int | None = None,
    now_ms: int | None = None,
    executor_armed: bool = False,
) -> SafetyEvaluation:
    now = now_ms if now_ms is not None else current_time_ms()
    checks = [
        _check(
            command,
            "ttl_not_expired",
            command.expires_at_ms > now,
            f"expires_at_ms={command.expires_at_ms}, now_ms={now}",
        ),
        _check(
            command,
            "ttl_within_config",
            command.ttl_ms <= config.command_ttl_ms,
            f"ttl_ms={command.ttl_ms}, max_ttl_ms={config.command_ttl_ms}",
        ),
        _check(
            command,
            "sequence_not_replayed",
            last_sequence_id is None or command.sequence_id > last_sequence_id,
            f"sequence_id={command.sequence_id}, last_sequence_id={last_sequence_id}",
        ),
        _check(
            command,
            "topic_allow_list",
            command.target_topic == config.allowed_topic,
            f"target_topic={command.target_topic}, allowed_topic={config.allowed_topic}",
        ),
        _check(
            command,
            "command_type_allow_list",
            command.command_type == "velocity_primitive",
            f"command_type={command.command_type}",
        ),
        _check(
            command,
            "declared_linear_limit",
            0 < command.max_linear_x <= config.max_linear_x,
            f"command_max_linear_x={command.max_linear_x}, config_max_linear_x={config.max_linear_x}",
        ),
        _check(
            command,
            "declared_angular_limit",
            0 < command.max_angular_z <= config.max_angular_z,
            f"command_max_angular_z={command.max_angular_z}, config_max_angular_z={config.max_angular_z}",
        ),
        _check(
            command,
            "linear_velocity_limit",
            abs(command.linear_x) <= min(command.max_linear_x, config.max_linear_x),
            f"linear_x={command.linear_x}, limit={min(command.max_linear_x, config.max_linear_x)}",
        ),
        _check(
            command,
            "angular_velocity_limit",
            abs(command.angular_z) <= min(command.max_angular_z, config.max_angular_z),
            f"angular_z={command.angular_z}, limit={min(command.max_angular_z, config.max_angular_z)}",
        ),
        _check(
            command,
            "duration_limit",
            command.duration_ms <= config.max_duration_ms,
            f"duration_ms={command.duration_ms}, max_duration_ms={config.max_duration_ms}",
        ),
        _check(
            command,
            "requires_stop_after",
            command.requires_stop_after,
            f"requires_stop_after={command.requires_stop_after}",
        ),
    ]

    if config.require_operator_armed:
        checks.extend(
            [
                _check(
                    command,
                    "operator_armed",
                    command.operator_armed,
                    f"operator_armed={command.operator_armed}",
                ),
                _check(
                    command,
                    "operator_approval_id_present",
                    bool(command.approval_id),
                    f"approval_id_present={bool(command.approval_id)}",
                ),
                _check(
                    command,
                    "executor_cli_armed",
                    executor_armed,
                    f"executor_cli_armed={executor_armed}",
                ),
            ]
        )

    failed = [check.check for check in checks if not check.passed]
    return SafetyEvaluation(
        accepted=not failed,
        rejected_reason=None if not failed else f"failed safety checks: {', '.join(failed)}",
        checks=checks,
    )


def _check(command: VerifiedCommand, name: str, passed: bool, detail: str) -> SafetyCheck:
    return SafetyCheck(
        command_id=command.command_id,
        sequence_id=command.sequence_id,
        check=name,
        passed=bool(passed),
        detail=detail,
    )


def _try_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

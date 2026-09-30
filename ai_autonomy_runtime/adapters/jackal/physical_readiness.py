from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from ai_autonomy_runtime.adapters.jackal.executor_safety import ExecutorSafetyConfig
from ai_autonomy_runtime.core.config import load_yaml
from ai_autonomy_runtime.schemas.verified_command import current_time_ms


DEFAULT_ACK_PHRASE = "I_ACK_LIMITED_PHYSICAL_EXECUTION_RISK"


class PhysicalReadinessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_ack_phrase: str = DEFAULT_ACK_PHRASE
    min_remote_suite_cases: int = Field(default=8, ge=1)
    min_live_samples: int = Field(default=1, ge=0)
    max_linear_x: float = Field(default=0.05, gt=0)
    max_angular_z: float = Field(default=0.15, gt=0)
    max_duration_ms: int = Field(default=700, gt=0)
    max_command_ttl_ms: int = Field(default=800, gt=0)
    require_env_enable: bool = True
    require_estop_available: bool = True
    require_safe_area_confirmed: bool = True
    require_deadman_tested: bool = True
    require_stop_policy_tested: bool = True
    require_inverted_bench: bool = False
    require_remote_suite_passed: bool = True
    require_live_observation: bool = True
    require_publish_disabled_all_in_suite: bool = True
    require_no_suite_execution: bool = True
    require_no_suite_ros_publish: bool = True

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PhysicalReadinessConfig":
        return cls.model_validate(load_yaml(path))


class ReadinessCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check: str
    passed: bool
    detail: str = ""


class PhysicalReadinessReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ready: bool
    reason: str
    checks: List[ReadinessCheck] = Field(default_factory=list)
    reviewed_at_ms: int = Field(default_factory=current_time_ms, ge=0)
    publish_disabled: bool = True
    ros_published: bool = False
    physical_execution_connected: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


def evaluate_limited_physical_readiness(
    *,
    config: PhysicalReadinessConfig,
    executor_config: ExecutorSafetyConfig,
    remote_suite_summary: Dict[str, Any],
    live_summary: Optional[Dict[str, Any]],
    operator_ack_text: str = "",
    estop_available: bool = False,
    safe_area_confirmed: bool = False,
    deadman_tested: bool = False,
    stop_policy_tested: bool = False,
    inverted_bench_confirmed: bool = False,
    env: Optional[Dict[str, str]] = None,
) -> PhysicalReadinessReview:
    env_values = env if env is not None else os.environ
    checks = [
        _check(
            "operator_ack_phrase",
            operator_ack_text == config.required_ack_phrase,
            f"required={config.required_ack_phrase!r}",
        ),
        _check(
            "enable_physical_execution_env",
            (not config.require_env_enable) or env_values.get("ENABLE_PHYSICAL_EXECUTION") == "1",
            "ENABLE_PHYSICAL_EXECUTION must be 1 for readiness.",
        ),
        _check(
            "estop_available",
            (not config.require_estop_available) or estop_available,
            f"estop_available={estop_available}",
        ),
        _check(
            "safe_area_confirmed",
            (not config.require_safe_area_confirmed) or safe_area_confirmed,
            f"safe_area_confirmed={safe_area_confirmed}",
        ),
        _check(
            "deadman_tested",
            (not config.require_deadman_tested) or deadman_tested,
            f"deadman_tested={deadman_tested}",
        ),
        _check(
            "stop_policy_tested",
            (not config.require_stop_policy_tested) or stop_policy_tested,
            f"stop_policy_tested={stop_policy_tested}",
        ),
        _check(
            "inverted_bench_confirmed",
            (not config.require_inverted_bench) or inverted_bench_confirmed,
            f"inverted_bench_confirmed={inverted_bench_confirmed}",
        ),
        _check(
            "remote_dryrun_suite_passed",
            (not config.require_remote_suite_passed) or bool(remote_suite_summary.get("suite_passed")),
            f"suite_passed={remote_suite_summary.get('suite_passed')}",
        ),
        _check(
            "remote_dryrun_suite_case_count",
            int(remote_suite_summary.get("case_count", 0)) >= config.min_remote_suite_cases,
            f"case_count={remote_suite_summary.get('case_count')}, min={config.min_remote_suite_cases}",
        ),
        _check(
            "remote_dryrun_suite_no_execution",
            (not config.require_no_suite_execution) or not bool(remote_suite_summary.get("executed_any")),
            f"executed_any={remote_suite_summary.get('executed_any')}",
        ),
        _check(
            "remote_dryrun_suite_no_ros_publish",
            (not config.require_no_suite_ros_publish) or not bool(remote_suite_summary.get("ros_published_any")),
            f"ros_published_any={remote_suite_summary.get('ros_published_any')}",
        ),
        _check(
            "remote_dryrun_suite_publish_disabled",
            (not config.require_publish_disabled_all_in_suite) or bool(remote_suite_summary.get("publish_disabled_all")),
            f"publish_disabled_all={remote_suite_summary.get('publish_disabled_all')}",
        ),
        _check(
            "executor_linear_limit_for_limited_physical",
            executor_config.max_linear_x <= config.max_linear_x,
            f"executor_max_linear_x={executor_config.max_linear_x}, readiness_max_linear_x={config.max_linear_x}",
        ),
        _check(
            "executor_angular_limit_for_limited_physical",
            executor_config.max_angular_z <= config.max_angular_z,
            f"executor_max_angular_z={executor_config.max_angular_z}, readiness_max_angular_z={config.max_angular_z}",
        ),
        _check(
            "executor_duration_limit_for_limited_physical",
            executor_config.max_duration_ms <= config.max_duration_ms,
            f"executor_max_duration_ms={executor_config.max_duration_ms}, readiness_max_duration_ms={config.max_duration_ms}",
        ),
        _check(
            "executor_ttl_limit_for_limited_physical",
            executor_config.command_ttl_ms <= config.max_command_ttl_ms,
            f"executor_ttl_ms={executor_config.command_ttl_ms}, readiness_max_ttl_ms={config.max_command_ttl_ms}",
        ),
    ]
    checks.extend(_live_observation_checks(config, live_summary))
    failed = [check.check for check in checks if not check.passed]
    return PhysicalReadinessReview(
        ready=not failed,
        reason="ready_for_limited_physical_execution" if not failed else f"failed readiness checks: {', '.join(failed)}",
        checks=checks,
        metadata={
            "remote_suite_output_dir": remote_suite_summary.get("output_dir"),
            "live_summary_run_dir": live_summary.get("run_dir") if live_summary else None,
            "required_ack_phrase": config.required_ack_phrase,
        },
    )


def load_readiness_review(path: str | Path) -> PhysicalReadinessReview:
    return PhysicalReadinessReview.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def readiness_report_allows_physical_execution(path: str | Path) -> tuple[bool, str]:
    try:
        review = load_readiness_review(path)
    except Exception as exc:
        return False, f"readiness_report_invalid: {exc}"
    if not review.ready:
        return False, f"readiness_report_not_ready: {review.reason}"
    if review.ros_published:
        return False, "readiness_report_invalid: ros_published must be false"
    if not review.publish_disabled:
        return False, "readiness_report_invalid: publish_disabled must be true during review"
    if review.physical_execution_connected:
        return False, "readiness_report_invalid: physical_execution_connected must be false during review"
    return True, "ok"


def _live_observation_checks(
    config: PhysicalReadinessConfig,
    live_summary: Optional[Dict[str, Any]],
) -> List[ReadinessCheck]:
    if not config.require_live_observation:
        return [_check("live_observation_required", True, "not required")]
    if live_summary is None:
        return [_check("live_observation_summary_present", False, "live summary was not provided")]
    sample_count = int(live_summary.get("sample_count", 0))
    return [
        _check("live_observation_summary_present", True, "live summary provided"),
        _check(
            "live_observation_stream_complete",
            bool(live_summary.get("stream_complete")),
            f"stream_complete={live_summary.get('stream_complete')}",
        ),
        _check(
            "live_observation_samples",
            sample_count >= config.min_live_samples,
            f"sample_count={sample_count}, min={config.min_live_samples}",
        ),
    ]


def _check(name: str, passed: bool, detail: str) -> ReadinessCheck:
    return ReadinessCheck(check=name, passed=bool(passed), detail=detail)

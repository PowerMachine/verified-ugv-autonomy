from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ai_autonomy_runtime.adapters.jackal.executor_safety import ExecutorSafetyConfig
from ai_autonomy_runtime.adapters.jackal.physical_readiness import (
    DEFAULT_ACK_PHRASE,
    PhysicalReadinessConfig,
    evaluate_limited_physical_readiness,
    readiness_report_allows_physical_execution,
)
from tests.verified_command_helpers import make_verified_command


def remote_suite_summary(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "suite_passed": True,
        "case_count": 8,
        "executed_any": False,
        "ros_published_any": False,
        "publish_disabled_all": True,
        "output_dir": "local_outputs/remote_executor_dryrun_suite/test",
    }
    data.update(overrides)
    return data


def live_summary(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "sample_count": 10,
        "stream_complete": True,
        "run_dir": "local_outputs/ugv_live/test",
    }
    data.update(overrides)
    return data


def test_readiness_rejects_without_operator_and_site_checks() -> None:
    review = evaluate_limited_physical_readiness(
        config=PhysicalReadinessConfig(),
        executor_config=ExecutorSafetyConfig(max_linear_x=0.05, max_duration_ms=700),
        remote_suite_summary=remote_suite_summary(),
        live_summary=live_summary(),
        env={"ENABLE_PHYSICAL_EXECUTION": "1"},
    )

    assert not review.ready
    failed = {check.check for check in review.checks if not check.passed}
    assert "operator_ack_phrase" in failed
    assert "estop_available" in failed
    assert "safe_area_confirmed" in failed


def test_readiness_accepts_when_all_limited_physical_gates_pass() -> None:
    review = evaluate_limited_physical_readiness(
        config=PhysicalReadinessConfig(),
        executor_config=ExecutorSafetyConfig(max_linear_x=0.05, max_duration_ms=700),
        remote_suite_summary=remote_suite_summary(),
        live_summary=live_summary(),
        operator_ack_text=DEFAULT_ACK_PHRASE,
        estop_available=True,
        safe_area_confirmed=True,
        deadman_tested=True,
        stop_policy_tested=True,
        env={"ENABLE_PHYSICAL_EXECUTION": "1"},
    )

    assert review.ready
    assert review.publish_disabled
    assert not review.ros_published
    assert not review.physical_execution_connected


def test_readiness_rejects_executor_limit_above_limited_physical_cap() -> None:
    review = evaluate_limited_physical_readiness(
        config=PhysicalReadinessConfig(max_linear_x=0.05),
        executor_config=ExecutorSafetyConfig(max_linear_x=0.08, max_duration_ms=700),
        remote_suite_summary=remote_suite_summary(),
        live_summary=live_summary(),
        operator_ack_text=DEFAULT_ACK_PHRASE,
        estop_available=True,
        safe_area_confirmed=True,
        deadman_tested=True,
        stop_policy_tested=True,
        env={"ENABLE_PHYSICAL_EXECUTION": "1"},
    )

    assert not review.ready
    assert "executor_linear_limit_for_limited_physical" in {check.check for check in review.checks if not check.passed}


def test_inverted_bench_profile_requires_bench_confirmation() -> None:
    review = evaluate_limited_physical_readiness(
        config=PhysicalReadinessConfig(require_inverted_bench=True),
        executor_config=ExecutorSafetyConfig(max_linear_x=0.05, max_duration_ms=700),
        remote_suite_summary=remote_suite_summary(),
        live_summary=live_summary(),
        operator_ack_text=DEFAULT_ACK_PHRASE,
        estop_available=True,
        safe_area_confirmed=True,
        deadman_tested=True,
        stop_policy_tested=True,
        env={"ENABLE_PHYSICAL_EXECUTION": "1"},
    )

    assert not review.ready
    assert "inverted_bench_confirmed" in {check.check for check in review.checks if not check.passed}


def test_readiness_report_loader_allows_only_ready_review(tmp_path: Path) -> None:
    review = evaluate_limited_physical_readiness(
        config=PhysicalReadinessConfig(),
        executor_config=ExecutorSafetyConfig(max_linear_x=0.05, max_duration_ms=700),
        remote_suite_summary=remote_suite_summary(),
        live_summary=live_summary(),
        operator_ack_text=DEFAULT_ACK_PHRASE,
        estop_available=True,
        safe_area_confirmed=True,
        deadman_tested=True,
        stop_policy_tested=True,
        env={"ENABLE_PHYSICAL_EXECUTION": "1"},
    )
    path = tmp_path / "readiness_review.json"
    path.write_text(json.dumps(review.model_dump(mode="json")), encoding="utf-8")

    allowed, reason = readiness_report_allows_physical_execution(path)

    assert allowed
    assert reason == "ok"


def test_verified_executor_cli_refuses_armed_without_readiness_report(tmp_path: Path) -> None:
    command_path = tmp_path / "verified_command.json"
    command_path.write_text(json.dumps(make_verified_command().model_dump(mode="json")), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ai_autonomy_runtime.cli.run_verified_executor",
            "--input-file",
            str(command_path),
            "--armed",
            "--state-file",
            str(tmp_path / "executor_state.json"),
            "--runs-dir",
            str(tmp_path / "runs"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    receipt = json.loads(result.stdout)
    assert receipt["accepted"] is False
    assert receipt["executed"] is False
    assert receipt["publish_disabled"] is True
    assert receipt["ros_published"] is False
    assert receipt["rejected_reason"] == "limited_physical_readiness_report_required"

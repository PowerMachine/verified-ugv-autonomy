from __future__ import annotations

import json
from pathlib import Path

from ai_autonomy_runtime.adapters.jackal.video_scenario_supervisor import (
    VideoScenarioSupervisor,
    run_video_scenario_supervisor,
)
from ai_autonomy_runtime.schemas.runtime_event import RuntimeEventType
from ai_autonomy_runtime.verifier.ugv_safety_validator import UGVSafetyValidator


def test_obstacle_ahead_becomes_dry_run_stop() -> None:
    scenario = _scenario(confidence=0.84, obstacle_detected=True)
    supervisor = VideoScenarioSupervisor(confidence_threshold=0.6)

    event = supervisor.event_from_scenario(scenario)
    candidate = supervisor.propose_action(event)
    verification = UGVSafetyValidator().validate(candidate)

    assert event.event_type == RuntimeEventType.PATH_BLOCKED.value
    assert candidate.action_type == "stop"
    assert candidate.requires_physical_execution is False
    assert candidate.parameters["supervisor_mode"] == "dry_run_only"
    assert verification.passed


def test_low_confidence_obstacle_reports_only() -> None:
    scenario = _scenario(confidence=0.32, obstacle_detected=True)
    supervisor = VideoScenarioSupervisor(confidence_threshold=0.6)

    event = supervisor.event_from_scenario(scenario)
    candidate = supervisor.propose_action(event)

    assert event.event_type == RuntimeEventType.CAMERA_OBSERVATION.value
    assert candidate.action_type == "report_only"
    assert candidate.requires_physical_execution is False


def test_no_obstacle_reports_only() -> None:
    scenario = _scenario(confidence=0.0, obstacle_detected=False)
    supervisor = VideoScenarioSupervisor(confidence_threshold=0.6)

    event = supervisor.event_from_scenario(scenario)
    candidate = supervisor.propose_action(event)

    assert event.event_type == RuntimeEventType.CAMERA_OBSERVATION.value
    assert candidate.action_type == "report_only"


def test_run_video_scenario_writes_visual_artifacts(tmp_path: Path) -> None:
    summary = run_video_scenario_supervisor(_scenario(confidence=0.84), tmp_path)

    assert summary["accepted"] is True
    assert summary["proposed_action"] == "stop"
    assert summary["ros_published"] is False
    assert summary["ssh_used"] is False
    assert summary["llm_used"] is False
    grid_path = Path(summary["scenario_grid_html"])
    trajectory_path = Path(summary["preview_trajectory_csv"])
    assert grid_path.exists()
    assert trajectory_path.exists()
    assert "Scenario grid and dry-run trajectory" in grid_path.read_text(encoding="utf-8")
    runtime_event = json.loads((tmp_path / "runtime_event.json").read_text(encoding="utf-8"))
    assert runtime_event["payload"]["fixture_only"] is True


def _scenario(confidence: float, obstacle_detected: bool = True) -> dict[str, object]:
    return {
        "scenario_id": "test_video_obstacle",
        "video_ref": "test_video.mp4",
        "frame_time_s": 2.5,
        "context": {
            "camera_is_live_on_robot": False,
            "ugv_is_inverted_bench": True,
            "physical_motion_synchronized": False,
        },
        "perception": {
            "obstacle_detected": obstacle_detected,
            "obstacle_label": "box",
            "confidence": confidence,
            "relative_position": "front",
            "estimated_distance_m": 1.2,
        },
    }

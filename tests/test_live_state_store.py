from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ai_autonomy_runtime.live.ugv_live_state import LiveStateStore


def test_live_state_placeholder_exists_before_first_sample(tmp_path: Path) -> None:
    store = LiveStateStore("test_run", tmp_path)
    snapshot = store.snapshot()

    assert (tmp_path / "live_state.json").exists()
    assert snapshot["sample_count"] == 0
    assert snapshot["status"] == "waiting"
    assert snapshot["last_state"] is None


def test_state_store_increments_sample_count_and_exports_csv(tmp_path: Path) -> None:
    store = LiveStateStore("test_run", tmp_path)
    store.apply_state(_sample_state(0, 100.0, 0.0))
    store.apply_state(_sample_state(1, 100.2, 0.01))

    snapshot = store.snapshot()
    assert snapshot["sample_count"] == 2
    assert snapshot["last_state"]["sample_idx"] == 1
    csv_text = (tmp_path / "trajectory.csv").read_text(encoding="utf-8")
    assert "x_m" in csv_text
    assert "0.010000" in csv_text


def test_stale_detection_after_timeout(tmp_path: Path) -> None:
    store = LiveStateStore("test_run", tmp_path, stale_after_s=0.01)
    store.apply_state(_sample_state(0, 100.0, 0.0))
    time.sleep(0.03)

    snapshot = store.snapshot()
    assert snapshot["stale"] is True
    assert snapshot["status"] == "stale"


def test_live_state_writes_are_thread_safe(tmp_path: Path) -> None:
    store = LiveStateStore("test_run", tmp_path)
    store.apply_state(_sample_state(0, 100.0, 0.0))

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _index: store.write_live_state(), range(40)))

    assert all(path.exists() for path in results)


def _sample_state(sample_idx: int, wall_time: float, x: float) -> dict[str, object]:
    return {
        "schema_version": "ugv_state.v1",
        "run_id": "test_run",
        "sample_idx": sample_idx,
        "wall_time": wall_time,
        "ros_time": wall_time,
        "source_pose_topic": "/jackal_velocity_controller/odom",
        "pose": {"x": x, "y": 0.0, "yaw": 0.0},
        "velocity": {"linear_x": 0.05, "angular_z": 0.0},
        "cmd_in": {"linear_x": 0.05, "angular_z": 0.0},
        "cmd_out": {"linear_x": 0.05, "angular_z": 0.0},
        "status": {"ros_connected": True, "odom_available": True},
    }

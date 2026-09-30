from __future__ import annotations

import csv
from pathlib import Path

from ai_autonomy_runtime.sandbox.ugv_2d_simulator import (
    UGV2DSimulator,
    load_twist_samples_from_capture_csv,
    write_path_csv,
    write_path_svg,
)


def test_fixed_forward_motion_integrates_distance() -> None:
    simulator = UGV2DSimulator()
    simulator.run_fixed(linear_x=0.1, angular_z=0.0, duration_s=2.0, dt_s=0.1)
    summary = simulator.summary()

    assert abs(float(summary["final_x_m"]) - 0.2) < 1e-6
    assert abs(float(summary["final_y_m"])) < 1e-6
    assert abs(float(summary["path_distance_m"]) - 0.2) < 1e-6


def test_capture_csv_auto_prefers_cmd_out(tmp_path: Path) -> None:
    path = tmp_path / "samples.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["t_s", "cmd_linear_x", "cmd_angular_z", "cmd_out_linear_x", "cmd_out_angular_z"],
        )
        writer.writeheader()
        writer.writerow(
            {
                "t_s": "0.0",
                "cmd_linear_x": "0.1",
                "cmd_angular_z": "0.0",
                "cmd_out_linear_x": "0.05",
                "cmd_out_angular_z": "0.0",
            }
        )
        writer.writerow(
            {
                "t_s": "1.0",
                "cmd_linear_x": "0.1",
                "cmd_angular_z": "0.0",
                "cmd_out_linear_x": "0.05",
                "cmd_out_angular_z": "0.0",
            }
        )

    samples = load_twist_samples_from_capture_csv(path)
    simulator = UGV2DSimulator()
    simulator.run_samples(samples)

    assert samples[0].source == "cmd_out"
    assert abs(float(simulator.summary()["final_x_m"]) - 0.05) < 1e-6


def test_path_outputs_are_written(tmp_path: Path) -> None:
    simulator = UGV2DSimulator()
    points = simulator.run_fixed(linear_x=0.1, angular_z=0.1, duration_s=1.0, dt_s=0.1)

    csv_path = write_path_csv(tmp_path / "trajectory.csv", points)
    svg_path = write_path_svg(tmp_path / "trajectory.svg", points)

    assert csv_path.exists()
    assert svg_path.exists()
    assert "polyline" in svg_path.read_text(encoding="utf-8")

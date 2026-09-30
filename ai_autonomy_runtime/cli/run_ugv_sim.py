from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from ai_autonomy_runtime.sandbox.ugv_2d_simulator import (
    UGV2DSimulator,
    command_to_twist,
    load_twist_samples_from_capture_csv,
    write_map_html,
    write_path_csv,
    write_path_svg,
    write_summary_json,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a lightweight 2D UGV motion simulation.")
    parser.add_argument("--output", default="runs/ugv_sim")
    parser.add_argument("--input-csv", help="CSV from capture_ugv_motion.")
    parser.add_argument("--source", choices=["auto", "cmd_out", "cmd", "odom_twist"], default="auto")
    parser.add_argument("--command", choices=["forward", "back", "left", "right", "stop"], default="forward")
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--linear", type=float, default=0.08)
    parser.add_argument("--angular", type=float, default=0.18)
    parser.add_argument("--dt", type=float, default=0.05)
    args = parser.parse_args()

    run_dir = _create_run_dir(args.output)
    simulator = UGV2DSimulator()
    if args.input_csv:
        samples = load_twist_samples_from_capture_csv(args.input_csv, source=args.source)
        points = simulator.run_samples(samples)
        input_mode = "capture_csv"
    else:
        linear_x, angular_z = command_to_twist(args.command, args.linear, args.angular)
        points = simulator.run_fixed(linear_x, angular_z, args.duration, dt_s=args.dt)
        input_mode = "fixed_command"

    simulation_summary = simulator.summary()
    path_csv = write_path_csv(run_dir / "trajectory.csv", points)
    path_svg = write_path_svg(run_dir / "trajectory.svg", points)
    map_html = write_map_html(run_dir / "map.html", points, simulation_summary)
    summary = {
        "run_dir": str(run_dir),
        "input_mode": input_mode,
        "input_csv": args.input_csv,
        "source": args.source,
        "command": args.command,
        "duration_s": args.duration,
        "linear_mps": args.linear,
        "angular_radps": args.angular,
        "dt_s": args.dt,
        "trajectory_csv": str(path_csv),
        "trajectory_svg": str(path_svg),
        "map_html": str(map_html),
        "simulation": simulation_summary,
    }
    write_summary_json(run_dir / "summary.json", summary)
    print_summary(summary)


def print_summary(summary: dict[str, object]) -> None:
    simulation = summary["simulation"]
    assert isinstance(simulation, dict)
    print(f"run_dir: {summary['run_dir']}")
    print(f"mode: {summary['input_mode']}")
    print(f"final_x_m: {simulation['final_x_m']:.4f}")
    print(f"final_y_m: {simulation['final_y_m']:.4f}")
    print(f"final_yaw_deg: {simulation['final_yaw_deg']:.2f}")
    print(f"path_distance_m: {simulation['path_distance_m']:.4f}")
    print(f"trajectory_svg: {summary['trajectory_svg']}")
    print(f"map_html: {summary['map_html']}")


def _create_run_dir(base_dir: str | Path) -> Path:
    base = Path(base_dir)
    run_dir = base / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


if __name__ == "__main__":
    main()

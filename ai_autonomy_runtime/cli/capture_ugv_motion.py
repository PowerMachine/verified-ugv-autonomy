from __future__ import annotations

import argparse
import csv
import json
import math
import select
import signal
import sys
import termios
import time
import tty
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_autonomy_runtime.sandbox.ugv_2d_simulator import (
    UGV2DSimulator,
    write_live_map_html,
    write_live_state_json,
    write_map_html,
    write_path_csv,
    write_path_svg,
)


@dataclass
class Latest:
    message: Any | None = None
    timestamp: float = 0.0
    count: int = 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture Jackal UGV motion topics for 2D simulation.")
    parser.add_argument("--output", default="runs/ugv_motion_capture")
    parser.add_argument("--run-id", help="Use a known run directory name instead of a timestamp.")
    parser.add_argument("--duration", type=float, default=5.0)
    parser.add_argument("--rate", type=float, default=20.0)
    parser.add_argument("--cmd-topic", default="/cmd_vel")
    parser.add_argument("--cmd-out-topic", default="/jackal_velocity_controller/cmd_vel_out")
    parser.add_argument("--odom-topic", default="/jackal_velocity_controller/odom")
    parser.add_argument("--feedback-topic", default="/feedback")
    parser.add_argument("--command", choices=["none", "forward", "back", "left", "right", "stop"], default="none")
    parser.add_argument("--interactive", action="store_true", help="Capture WASD control instead of a fixed command.")
    parser.add_argument("--start-on-key", action="store_true", help="Start the capture timer on the first interactive key.")
    parser.add_argument("--live-sim", action="store_true", help="Show a live terminal 2D pose estimate while capturing.")
    parser.add_argument("--live-state", action="store_true", help="Continuously write live_state.json.")
    parser.add_argument("--live-map", action="store_true", help="Write live_map.html for browser-based live viewing.")
    parser.add_argument("--no-render-artifacts", action="store_true", help="Skip trajectory/map files on the Jetson.")
    parser.add_argument("--sim-source", choices=["cmd_out", "cmd", "odom_twist"], default="cmd_out")
    parser.add_argument("--render-rate", type=float, default=4.0)
    parser.add_argument("--linear", type=float, default=0.08)
    parser.add_argument("--angular", type=float, default=0.18)
    parser.add_argument("--max-linear", type=float, default=0.1)
    parser.add_argument("--max-angular", type=float, default=0.2)
    parser.add_argument("--armed", action="store_true")
    args = parser.parse_args()

    if args.interactive and args.command != "none":
        raise SystemExit("Use either --interactive or --command, not both.")
    if (args.command != "none" or args.interactive) and not args.armed:
        raise SystemExit("Refusing to publish motion without --armed.")

    rospy, rostopic, Twist = _load_ros()
    rospy.init_node("ai_autonomy_ugv_motion_capture", anonymous=True)
    signal.signal(signal.SIGINT, lambda _signum, _frame: rospy.signal_shutdown("interrupted"))
    signal.signal(signal.SIGTERM, lambda _signum, _frame: rospy.signal_shutdown("terminated"))

    run_dir = _create_run_dir(args.output, args.run_id)
    events_path = run_dir / "events.jsonl"
    samples_path = run_dir / "samples.csv"
    live_state_path = run_dir / "live_state.json"
    if args.live_map:
        write_live_map_html(run_dir / "live_map.html", refresh_ms=max(100, int(1000.0 / max(args.render_rate, 0.1))))

    latest_cmd = Latest()
    latest_cmd_out = Latest()
    latest_odom = Latest()
    latest_feedback = Latest()

    _subscribe(rospy, rostopic, args.cmd_topic, latest_cmd, events_path, "cmd")
    _subscribe(rospy, rostopic, args.cmd_out_topic, latest_cmd_out, events_path, "cmd_out")
    _subscribe(rospy, rostopic, args.odom_topic, latest_odom, events_path, "odom")
    _subscribe(rospy, rostopic, args.feedback_topic, latest_feedback, events_path, "feedback")

    publisher = None
    if args.command != "none" or args.interactive:
        publisher = rospy.Publisher(args.cmd_topic, Twist, queue_size=1)
        _wait_for_subscribers(rospy, publisher, args.cmd_topic, 3.0)

    fieldnames = [
        "t_s",
        "cmd_linear_x",
        "cmd_angular_z",
        "cmd_out_linear_x",
        "cmd_out_angular_z",
        "odom_x",
        "odom_y",
        "odom_yaw",
        "odom_linear_x",
        "odom_angular_z",
        "feedback_left_velocity",
        "feedback_right_velocity",
        "feedback_left_duty",
        "feedback_right_duty",
    ]

    linear_x, angular_z = _command_to_twist(
        args.command,
        _clamp_abs(args.linear, args.max_linear),
        _clamp_abs(args.angular, args.max_angular),
    )
    interactive_linear = _clamp_abs(args.linear, args.max_linear)
    interactive_angular = _clamp_abs(args.angular, args.max_angular)
    current_linear_x, current_angular_z = linear_x, angular_z
    settings = None
    if args.interactive:
        settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())
        print("W/S forward/back, A/D turn, X or Space stop, Q quit", flush=True)
        if args.start_on_key:
            print("Timer starts on the first key.", flush=True)

    simulator = UGV2DSimulator()
    live_metadata = {
        "cmd_topic": args.cmd_topic,
        "cmd_out_topic": args.cmd_out_topic,
        "odom_topic": args.odom_topic,
        "feedback_topic": args.feedback_topic,
        "sim_source": args.sim_source,
    }
    if args.live_state or args.live_map:
        write_live_state_json(live_state_path, simulator.path, simulator.summary(), live_metadata, complete=False)
    started: float | None = None if args.interactive and args.start_on_key else time.monotonic()
    last_step = started or time.monotonic()
    last_render = 0.0
    should_quit = False
    rate = rospy.Rate(args.rate)
    rows_written = 0
    try:
        with samples_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            while not rospy.is_shutdown() and not should_quit and (
                started is None or (time.monotonic() - started) < args.duration
            ):
                now = time.monotonic()
                if args.interactive and select.select([sys.stdin], [], [], 0.0)[0]:
                    key = sys.stdin.read(1).lower()
                    if key == "q":
                        should_quit = True
                    else:
                        current_linear_x, current_angular_z = _key_to_twist(
                            key,
                            interactive_linear,
                            interactive_angular,
                            current_linear_x,
                            current_angular_z,
                        )
                    if started is None and (should_quit or _is_control_key(key)):
                        started = now
                        last_step = now
                        print("capture started", flush=True)
                    if not args.live_sim:
                        _render_key_status(key, current_linear_x, current_angular_z)
                if started is None:
                    if publisher is not None:
                        _publish_twist(publisher, Twist, 0.0, 0.0)
                    time.sleep(0.02)
                    continue
                if publisher is not None:
                    _publish_twist(publisher, Twist, current_linear_x, current_angular_z)
                row = _sample_row(now - started, latest_cmd, latest_cmd_out, latest_odom, latest_feedback)
                writer.writerow(row)
                rows_written += 1

                dt_s = now - last_step
                sim_linear_x, sim_angular_z = _select_sim_twist(row, args.sim_source)
                simulator.step(sim_linear_x, sim_angular_z, dt_s, source=args.sim_source)
                last_step = now
                if now - last_render >= 1.0 / max(args.render_rate, 0.1):
                    if args.live_sim:
                        _render_live_sim(simulator, args.sim_source, sim_linear_x, sim_angular_z)
                    if args.live_state or args.live_map:
                        write_live_state_json(
                            live_state_path,
                            simulator.path,
                            simulator.summary(),
                            live_metadata,
                            complete=False,
                        )
                    last_render = now
                rate.sleep()
    finally:
        if settings is not None:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)

    if publisher is not None:
        stop_started = time.monotonic()
        while not rospy.is_shutdown() and time.monotonic() - stop_started < 0.3:
            _publish_twist(publisher, Twist, 0.0, 0.0)
            time.sleep(0.05)

    simulation_summary = simulator.summary()
    trajectory_csv = None
    trajectory_svg = None
    map_html = None
    if not args.no_render_artifacts:
        trajectory_csv = write_path_csv(run_dir / "trajectory.csv", simulator.path)
        trajectory_svg = write_path_svg(run_dir / "trajectory.svg", simulator.path)
        map_html = write_map_html(run_dir / "map.html", simulator.path, simulation_summary)
    if args.live_state or args.live_map:
        write_live_state_json(live_state_path, simulator.path, simulation_summary, live_metadata, complete=True)
    summary = {
        "run_dir": str(run_dir),
        "samples_csv": str(samples_path),
        "events_jsonl": str(events_path),
        "trajectory_csv": str(trajectory_csv) if trajectory_csv else None,
        "trajectory_svg": str(trajectory_svg) if trajectory_svg else None,
        "map_html": str(map_html) if map_html else None,
        "live_map_html": str(run_dir / "live_map.html") if args.live_map else None,
        "live_state_json": str(live_state_path) if args.live_state or args.live_map else None,
        "duration_s": args.duration,
        "rate_hz": args.rate,
        "command": args.command,
        "interactive": args.interactive,
        "live_sim": args.live_sim,
        "sim_source": args.sim_source,
        "linear_x": linear_x,
        "angular_z": angular_z,
        "rows_written": rows_written,
        "simulation": simulation_summary,
        "messages": {
            "cmd": latest_cmd.count,
            "cmd_out": latest_cmd_out.count,
            "odom": latest_odom.count,
            "feedback": latest_feedback.count,
        },
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.live_sim or args.interactive:
        print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print()
    print("Windows PowerShell에서 결과 가져오기:")
    print(f"scp -r robot@192.0.2.10:~/ai-autonomy-ugv/{run_dir.as_posix()} .\\")


def _load_ros() -> tuple[Any, Any, Any]:
    try:
        import rospy
        import rostopic
        from geometry_msgs.msg import Twist
    except ImportError as exc:
        raise SystemExit("ROS1 Python modules are unavailable. Run: source /opt/ros/noetic/setup.bash") from exc
    return rospy, rostopic, Twist


def _subscribe(rospy: Any, rostopic: Any, topic: str, latest: Latest, events_path: Path, label: str) -> None:
    msg_class, real_topic, _ = rostopic.get_topic_class(topic, blocking=False)
    if msg_class is None:
        _append_event(events_path, {"event": "topic_unavailable", "label": label, "topic": topic})
        print(f"Watch topic unavailable: {topic}")
        return

    def callback(message: Any) -> None:
        latest.message = message
        latest.timestamp = time.monotonic()
        latest.count += 1
        if latest.count <= 3:
            _append_event(events_path, {"event": "message_seen", "label": label, "topic": real_topic, "count": latest.count})

    rospy.Subscriber(real_topic, msg_class, callback, queue_size=1)


def _sample_row(t_s: float, cmd: Latest, cmd_out: Latest, odom: Latest, feedback: Latest) -> dict[str, str]:
    cmd_linear, cmd_angular = _extract_twist(cmd.message)
    cmd_out_linear, cmd_out_angular = _extract_twist(cmd_out.message)
    odom_x, odom_y, odom_yaw, odom_linear, odom_angular = _extract_odom(odom.message)
    left_vel, right_vel, left_duty, right_duty = _extract_feedback(feedback.message)
    return {
        "t_s": f"{t_s:.6f}",
        "cmd_linear_x": f"{cmd_linear:.6f}",
        "cmd_angular_z": f"{cmd_angular:.6f}",
        "cmd_out_linear_x": f"{cmd_out_linear:.6f}",
        "cmd_out_angular_z": f"{cmd_out_angular:.6f}",
        "odom_x": f"{odom_x:.6f}",
        "odom_y": f"{odom_y:.6f}",
        "odom_yaw": f"{odom_yaw:.6f}",
        "odom_linear_x": f"{odom_linear:.6f}",
        "odom_angular_z": f"{odom_angular:.6f}",
        "feedback_left_velocity": f"{left_vel:.6f}",
        "feedback_right_velocity": f"{right_vel:.6f}",
        "feedback_left_duty": f"{left_duty:.6f}",
        "feedback_right_duty": f"{right_duty:.6f}",
    }


def _extract_twist(message: Any) -> tuple[float, float]:
    if message is None:
        return 0.0, 0.0
    twist = message
    if hasattr(message, "twist"):
        twist = message.twist
        if hasattr(twist, "twist"):
            twist = twist.twist
    return (
        float(getattr(getattr(twist, "linear", object()), "x", 0.0)),
        float(getattr(getattr(twist, "angular", object()), "z", 0.0)),
    )


def _extract_odom(message: Any) -> tuple[float, float, float, float, float]:
    if message is None:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    pose = message.pose.pose
    twist = message.twist.twist
    yaw = _yaw_from_quaternion(pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w)
    return (
        float(pose.position.x),
        float(pose.position.y),
        yaw,
        float(twist.linear.x),
        float(twist.angular.z),
    )


def _extract_feedback(message: Any) -> tuple[float, float, float, float]:
    if message is None or not hasattr(message, "drivers") or len(message.drivers) < 2:
        return 0.0, 0.0, 0.0, 0.0
    left = message.drivers[0]
    right = message.drivers[1]
    return (
        float(getattr(left, "measured_velocity", 0.0)),
        float(getattr(right, "measured_velocity", 0.0)),
        float(getattr(left, "duty_cycle", 0.0)),
        float(getattr(right, "duty_cycle", 0.0)),
    )


def _yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def _command_to_twist(command: str, linear: float, angular: float) -> tuple[float, float]:
    if command == "forward":
        return abs(linear), 0.0
    if command == "back":
        return -abs(linear), 0.0
    if command == "left":
        return 0.0, abs(angular)
    if command == "right":
        return 0.0, -abs(angular)
    return 0.0, 0.0


def _key_to_twist(
    key: str,
    linear: float,
    angular: float,
    current_linear_x: float,
    current_angular_z: float,
) -> tuple[float, float]:
    if key == "w":
        return linear, 0.0
    if key == "s":
        return -linear, 0.0
    if key == "a":
        return current_linear_x, angular
    if key == "d":
        return current_linear_x, -angular
    if key in {"x", " "}:
        return 0.0, 0.0
    return current_linear_x, current_angular_z


def _is_control_key(key: str) -> bool:
    return key in {"w", "s", "a", "d", "x", " ", "q"}


def _select_sim_twist(row: dict[str, str], source: str) -> tuple[float, float]:
    candidates = {
        "cmd_out": ("cmd_out_linear_x", "cmd_out_angular_z"),
        "cmd": ("cmd_linear_x", "cmd_angular_z"),
        "odom_twist": ("odom_linear_x", "odom_angular_z"),
    }
    linear_key, angular_key = candidates[source]
    return _float(row.get(linear_key)), _float(row.get(angular_key))


def _render_live_sim(simulator: UGV2DSimulator, source: str, linear_x: float, angular_z: float) -> None:
    summary = simulator.summary()
    print(
        "\r"
        f"live sim[{source}] "
        f"x={float(summary['final_x_m']): .3f}m "
        f"y={float(summary['final_y_m']): .3f}m "
        f"yaw={float(summary['final_yaw_deg']): .1f}deg "
        f"v={linear_x: .3f} "
        f"w={angular_z: .3f}     ",
        end="",
        flush=True,
    )


def _render_key_status(key: str, linear_x: float, angular_z: float) -> None:
    label = "space" if key == " " else key
    if key == "q":
        text = "quit requested"
    else:
        text = f"key={label} linear.x={linear_x: .3f} angular.z={angular_z: .3f}"
    print(f"\r{text}     ", end="", flush=True)


def _publish_twist(publisher: Any, Twist: Any, linear_x: float, angular_z: float) -> None:
    message = Twist()
    message.linear.x = linear_x
    message.angular.z = angular_z
    publisher.publish(message)


def _wait_for_subscribers(rospy: Any, publisher: Any, topic: str, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while not rospy.is_shutdown() and time.monotonic() < deadline:
        count = publisher.get_num_connections()
        if count > 0:
            print(f"{topic} subscriber connections: {count}")
            return
        time.sleep(0.05)
    print(f"Warning: {topic} has no subscribers after {timeout_s:.1f}s.")


def _clamp_abs(value: float, limit: float) -> float:
    return max(-abs(limit), min(abs(limit), abs(value)))


def _float(value: str | None) -> float:
    if value in {None, ""}:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def _append_event(path: Path, event: dict[str, Any]) -> None:
    payload = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def _create_run_dir(base_dir: str | Path, run_id: str | None = None) -> Path:
    base = Path(base_dir)
    run_dir = base / (run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


if __name__ == "__main__":
    main()

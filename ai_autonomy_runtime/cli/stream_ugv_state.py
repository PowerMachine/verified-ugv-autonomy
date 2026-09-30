from __future__ import annotations

import argparse
import json
import math
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

STATE_PREFIX = "UGV_STATE_JSON "
EVENT_PREFIX = "UGV_EVENT_JSON "


@dataclass
class LatestTopic:
    topic: str
    label: str
    message: Any | None = None
    timestamp_monotonic: float = 0.0
    count: int = 0
    subscribed: bool = False
    msg_class: Any | None = None
    real_topic: str | None = None
    missing_reported: bool = False


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream read-only Jackal UGV state as prefixed JSONL.")
    parser.add_argument("--run-id", default=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    parser.add_argument("--sample-hz", type=float, default=5.0)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--pose-topic", default="/jackal_velocity_controller/odom")
    parser.add_argument("--cmd-topic", default="/cmd_vel")
    parser.add_argument("--cmd-out-topic", default="/jackal_velocity_controller/cmd_vel_out")
    parser.add_argument("--feedback-topic", default="/feedback")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    try:
        rospy, rostopic = _load_ros()
    except ImportError as exc:
        _emit_event(
            {
                "event_type": "ros_import_failed",
                "severity": "error",
                "time": time.time(),
                "message": "ROS1 Python modules are unavailable. Source /opt/ros/noetic/setup.bash before running.",
            }
        )
        raise SystemExit(2) from exc

    rospy.init_node("ai_autonomy_ugv_state_stream", anonymous=True, disable_signals=True)
    stop_requested = False

    def request_stop(_signum: int, _frame: Any) -> None:
        nonlocal stop_requested
        stop_requested = True
        rospy.signal_shutdown("interrupted")

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)

    pose_topics = _unique([args.pose_topic, "/odometry/filtered"])
    pose_watchers = [LatestTopic(topic=topic, label="pose") for topic in pose_topics]
    cmd_in = LatestTopic(topic=args.cmd_topic, label="cmd_in")
    cmd_out = LatestTopic(topic=args.cmd_out_topic, label="cmd_out")
    feedback = LatestTopic(topic=args.feedback_topic, label="feedback")
    watchers = pose_watchers + [cmd_in, cmd_out, feedback]

    sample_period_s = 1.0 / max(args.sample_hz, 0.1)
    started = time.monotonic()
    next_retry = 0.0
    sample_idx = 0
    while not rospy.is_shutdown() and not stop_requested:
        now = time.monotonic()
        if now >= next_retry:
            for watcher in watchers:
                _ensure_subscription(rospy, rostopic, watcher, quiet=args.quiet)
            next_retry = now + 1.0
        selected_pose = _select_pose_topic(pose_watchers, preferred_topic=args.pose_topic)
        state = _build_state(rospy, args.run_id, sample_idx, selected_pose, pose_watchers, cmd_in, cmd_out, feedback)
        _emit_state(state)
        sample_idx += 1
        if args.duration > 0 and (time.monotonic() - started) >= args.duration:
            break
        _sleep_until_next_sample(rospy, sample_period_s)

    if not args.quiet:
        _emit_event({"event_type": "stream_complete", "severity": "info", "time": time.time(), "samples": sample_idx})


def _load_ros() -> tuple[Any, Any]:
    import rospy
    import rostopic

    return rospy, rostopic


def _ensure_subscription(rospy: Any, rostopic: Any, watcher: LatestTopic, quiet: bool) -> None:
    if watcher.subscribed:
        return
    try:
        msg_class, real_topic, _ = rostopic.get_topic_class(watcher.topic, blocking=False)
    except Exception as exc:
        if not watcher.missing_reported and not quiet:
            _emit_event(
                {
                    "event_type": "topic_lookup_failed",
                    "topic": watcher.topic,
                    "label": watcher.label,
                    "severity": "warning",
                    "time": time.time(),
                    "error": str(exc),
                }
            )
            watcher.missing_reported = True
        return
    if msg_class is None:
        if not watcher.missing_reported and not quiet:
            _emit_event(
                {
                    "event_type": "topic_missing",
                    "topic": watcher.topic,
                    "label": watcher.label,
                    "severity": "warning",
                    "time": time.time(),
                }
            )
            watcher.missing_reported = True
        return

    def callback(message: Any) -> None:
        watcher.message = message
        watcher.timestamp_monotonic = time.monotonic()
        watcher.count += 1

    watcher.msg_class = msg_class
    watcher.real_topic = real_topic
    watcher.subscribed = True
    rospy.Subscriber(real_topic, msg_class, callback, queue_size=1)
    if not quiet:
        _emit_event(
            {
                "event_type": "topic_subscribed",
                "topic": real_topic,
                "requested_topic": watcher.topic,
                "label": watcher.label,
                "severity": "info",
                "time": time.time(),
            }
        )


def _build_state(
    rospy: Any,
    run_id: str,
    sample_idx: int,
    selected_pose: LatestTopic | None,
    pose_watchers: list[LatestTopic],
    cmd_in: LatestTopic,
    cmd_out: LatestTopic,
    feedback: LatestTopic,
) -> dict[str, Any]:
    pose, velocity = _extract_pose_and_velocity(selected_pose.message if selected_pose else None)
    return {
        "schema_version": "ugv_state.v1",
        "run_id": run_id,
        "sample_idx": sample_idx,
        "wall_time": time.time(),
        "ros_time": _ros_time(rospy),
        "source_pose_topic": (selected_pose.real_topic or selected_pose.topic) if selected_pose else None,
        "pose": pose,
        "velocity": velocity,
        "cmd_in": _extract_twist(cmd_in.message),
        "cmd_out": _extract_twist(cmd_out.message),
        "feedback": _extract_feedback(feedback.message),
        "status": {
            "ros_connected": True,
            "odom_available": any(watcher.count > 0 for watcher in pose_watchers),
            "pose_topics_subscribed": [watcher.real_topic or watcher.topic for watcher in pose_watchers if watcher.subscribed],
            "cmd_in_available": cmd_in.count > 0,
            "cmd_out_available": cmd_out.count > 0,
            "feedback_available": feedback.count > 0,
            "topic_message_counts": {
                "pose": sum(watcher.count for watcher in pose_watchers),
                "cmd_in": cmd_in.count,
                "cmd_out": cmd_out.count,
                "feedback": feedback.count,
            },
        },
    }


def _select_pose_topic(pose_watchers: list[LatestTopic], preferred_topic: str) -> LatestTopic | None:
    preferred = next((watcher for watcher in pose_watchers if watcher.topic == preferred_topic and watcher.count > 0), None)
    if preferred is not None:
        return preferred
    available = [watcher for watcher in pose_watchers if watcher.count > 0]
    if not available:
        return None
    return max(available, key=lambda watcher: watcher.timestamp_monotonic)


def _extract_pose_and_velocity(message: Any | None) -> tuple[dict[str, float] | None, dict[str, float] | None]:
    if message is None or not hasattr(message, "pose"):
        return None, None
    pose_msg = getattr(message.pose, "pose", message.pose)
    position = getattr(pose_msg, "position", None)
    orientation = getattr(pose_msg, "orientation", None)
    if position is None or orientation is None:
        return None, None
    twist_msg = getattr(getattr(message, "twist", None), "twist", getattr(message, "twist", None))
    linear = getattr(twist_msg, "linear", None)
    angular = getattr(twist_msg, "angular", None)
    pose = {
        "x": float(getattr(position, "x", 0.0)),
        "y": float(getattr(position, "y", 0.0)),
        "yaw": _yaw_from_quaternion(
            float(getattr(orientation, "x", 0.0)),
            float(getattr(orientation, "y", 0.0)),
            float(getattr(orientation, "z", 0.0)),
            float(getattr(orientation, "w", 1.0)),
        ),
    }
    velocity = {
        "linear_x": float(getattr(linear, "x", 0.0)) if linear is not None else 0.0,
        "angular_z": float(getattr(angular, "z", 0.0)) if angular is not None else 0.0,
    }
    return pose, velocity


def _extract_twist(message: Any | None) -> dict[str, float] | None:
    if message is None:
        return None
    twist = message
    if hasattr(message, "twist"):
        twist = message.twist
        if hasattr(twist, "twist"):
            twist = twist.twist
    return {
        "linear_x": float(getattr(getattr(twist, "linear", object()), "x", 0.0)),
        "angular_z": float(getattr(getattr(twist, "angular", object()), "z", 0.0)),
    }


def _extract_feedback(message: Any | None) -> dict[str, float] | None:
    if message is None or not hasattr(message, "drivers") or len(message.drivers) < 2:
        return None
    left = message.drivers[0]
    right = message.drivers[1]
    return {
        "left_velocity": float(getattr(left, "measured_velocity", 0.0)),
        "right_velocity": float(getattr(right, "measured_velocity", 0.0)),
        "left_duty": float(getattr(left, "duty_cycle", 0.0)),
        "right_duty": float(getattr(right, "duty_cycle", 0.0)),
    }


def _ros_time(rospy: Any) -> float:
    try:
        return float(rospy.Time.now().to_sec())
    except Exception:
        return time.time()


def _yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def _sleep_until_next_sample(rospy: Any, period_s: float) -> None:
    deadline = time.monotonic() + period_s
    while not rospy.is_shutdown() and time.monotonic() < deadline:
        time.sleep(min(0.02, deadline - time.monotonic()))


def _emit_state(payload: dict[str, Any]) -> None:
    sys.stdout.write(STATE_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _emit_event(payload: dict[str, Any]) -> None:
    sys.stdout.write(EVENT_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


if __name__ == "__main__":
    main()

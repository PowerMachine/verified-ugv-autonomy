from __future__ import annotations

import argparse
import select
import signal
import sys
import termios
import time
import tty
from dataclasses import dataclass
from typing import Any


DEFAULT_MAX_LINEAR_MPS = 0.1
DEFAULT_MAX_ANGULAR_RADPS = 0.2


@dataclass
class LatestMessage:
    message: Any | None = None
    timestamp: float = 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely publish low-speed Jackal Twist commands.")
    parser.add_argument("--topic", default="/cmd_vel", help="Twist command topic to publish.")
    parser.add_argument(
        "--command",
        choices=["forward", "back", "left", "right", "stop"],
        default="stop",
        help="One-shot direction command.",
    )
    parser.add_argument("--interactive", action="store_true", help="Use WASD keyboard control.")
    parser.add_argument("--duration", type=float, default=1.0, help="One-shot command duration in seconds.")
    parser.add_argument("--linear", type=float, default=0.08, help="Linear speed magnitude in m/s.")
    parser.add_argument("--angular", type=float, default=0.18, help="Angular speed magnitude in rad/s.")
    parser.add_argument("--max-linear", type=float, default=DEFAULT_MAX_LINEAR_MPS)
    parser.add_argument("--max-angular", type=float, default=DEFAULT_MAX_ANGULAR_RADPS)
    parser.add_argument("--rate", type=float, default=20.0, help="Publish rate in Hz.")
    parser.add_argument("--connect-timeout", type=float, default=3.0)
    parser.add_argument("--watch-topic", default="/jackal_velocity_controller/cmd_vel_out")
    parser.add_argument("--odom-topic", default="/jackal_velocity_controller/odom")
    parser.add_argument("--armed", action="store_true", help="Required acknowledgement before publishing motion.")
    args = parser.parse_args()

    if not args.armed:
        raise SystemExit("Refusing to publish motion without --armed.")

    rospy, Twist, rostopic = _load_ros()
    rospy.init_node("ai_autonomy_ugv_teleop", anonymous=True)

    linear = _clamp_abs(args.linear, args.max_linear)
    angular = _clamp_abs(args.angular, args.max_angular)
    publisher = rospy.Publisher(args.topic, Twist, queue_size=1)

    latest_watch = LatestMessage()
    latest_odom = LatestMessage()
    _subscribe_if_available(rospy, rostopic, args.watch_topic, latest_watch)
    _subscribe_if_available(rospy, rostopic, args.odom_topic, latest_odom)

    def stop() -> None:
        _publish_twist(rospy, publisher, Twist, 0.0, 0.0, max(args.rate, 1.0), 0.2)

    rospy.on_shutdown(stop)
    signal.signal(signal.SIGINT, lambda _signum, _frame: rospy.signal_shutdown("interrupted"))
    signal.signal(signal.SIGTERM, lambda _signum, _frame: rospy.signal_shutdown("terminated"))

    _wait_for_subscribers(rospy, publisher, args.topic, args.connect_timeout)

    print(
        f"Publishing to {args.topic} with clamp linear<= {args.max_linear:.3f} m/s, "
        f"angular<= {args.max_angular:.3f} rad/s"
    )
    try:
        if args.interactive:
            _interactive_loop(rospy, publisher, Twist, linear, angular, args.rate)
        else:
            linear_x, angular_z = _command_to_twist(args.command, linear, angular)
            _publish_twist(rospy, publisher, Twist, linear_x, angular_z, args.rate, args.duration)
    finally:
        stop()
        time.sleep(0.1)
        _print_latest("watch", args.watch_topic, latest_watch)
        _print_latest("odom", args.odom_topic, latest_odom)


def _load_ros() -> tuple[Any, Any, Any]:
    try:
        import rospy
        import rostopic
        from geometry_msgs.msg import Twist
    except ImportError as exc:
        raise SystemExit(
            "ROS1 Python modules are unavailable. Run: source /opt/ros/noetic/setup.bash"
        ) from exc
    return rospy, Twist, rostopic


def _subscribe_if_available(rospy: Any, rostopic: Any, topic: str, latest: LatestMessage) -> None:
    msg_class, real_topic, _ = rostopic.get_topic_class(topic, blocking=False)
    if msg_class is None:
        print(f"Watch topic unavailable: {topic}")
        return

    def callback(message: Any) -> None:
        latest.message = message
        latest.timestamp = time.time()

    rospy.Subscriber(real_topic, msg_class, callback, queue_size=1)


def _wait_for_subscribers(rospy: Any, publisher: Any, topic: str, timeout_s: float) -> None:
    deadline = time.time() + timeout_s
    while not rospy.is_shutdown() and time.time() < deadline:
        count = publisher.get_num_connections()
        if count > 0:
            print(f"{topic} subscriber connections: {count}")
            return
        time.sleep(0.05)
    print(f"Warning: {topic} has no subscribers after {timeout_s:.1f}s.")


def _interactive_loop(rospy: Any, publisher: Any, Twist: Any, linear: float, angular: float, rate_hz: float) -> None:
    print("W/S forward/back, A/D turn, X or Space stop, Q quit")
    settings = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())
    current = (0.0, 0.0)
    rate = rospy.Rate(rate_hz)
    try:
        while not rospy.is_shutdown():
            if select.select([sys.stdin], [], [], 0.0)[0]:
                key = sys.stdin.read(1).lower()
                if key == "q":
                    break
                current = _key_to_twist(key, linear, angular, current)
            message = Twist()
            message.linear.x = current[0]
            message.angular.z = current[1]
            publisher.publish(message)
            rate.sleep()
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)


def _key_to_twist(key: str, linear: float, angular: float, current: tuple[float, float]) -> tuple[float, float]:
    if key == "w":
        return linear, 0.0
    if key == "s":
        return -linear, 0.0
    if key == "a":
        return current[0], angular
    if key == "d":
        return current[0], -angular
    if key in {"x", " "}:
        return 0.0, 0.0
    return current


def _command_to_twist(command: str, linear: float, angular: float) -> tuple[float, float]:
    if command == "forward":
        return linear, 0.0
    if command == "back":
        return -linear, 0.0
    if command == "left":
        return 0.0, angular
    if command == "right":
        return 0.0, -angular
    return 0.0, 0.0


def _publish_twist(
    rospy: Any,
    publisher: Any,
    Twist: Any,
    linear_x: float,
    angular_z: float,
    rate_hz: float,
    duration_s: float,
) -> None:
    rate = rospy.Rate(rate_hz)
    deadline = time.time() + max(duration_s, 0.0)
    while not rospy.is_shutdown() and time.time() < deadline:
        message = Twist()
        message.linear.x = linear_x
        message.angular.z = angular_z
        publisher.publish(message)
        rate.sleep()


def _clamp_abs(value: float, limit: float) -> float:
    return max(-abs(limit), min(abs(limit), abs(value)))


def _print_latest(label: str, topic: str, latest: LatestMessage) -> None:
    if latest.message is None:
        print(f"No {label} message observed on {topic}.")
        return
    linear_x, angular_z = _extract_twist(latest.message)
    age = time.time() - latest.timestamp
    print(f"Latest {label} {topic}: linear.x={linear_x:.4f}, angular.z={angular_z:.4f}, age={age:.2f}s")


def _extract_twist(message: Any) -> tuple[float, float]:
    twist = message
    if hasattr(message, "twist"):
        twist = message.twist
        if hasattr(twist, "twist"):
            twist = twist.twist
    linear_x = float(getattr(getattr(twist, "linear", object()), "x", 0.0))
    angular_z = float(getattr(getattr(twist, "angular", object()), "z", 0.0))
    return linear_x, angular_z


if __name__ == "__main__":
    main()

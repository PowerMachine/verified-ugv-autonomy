from __future__ import annotations

import json
import math
from html import escape
from pathlib import Path
from typing import Any, Mapping, Sequence

from ai_autonomy_runtime.sandbox.ugv_2d_simulator import (
    SimPoint,
    UGV2DSimulator,
    write_map_html,
    write_path_csv,
)
from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate
from ai_autonomy_runtime.schemas.common import RiskLevel, Severity
from ai_autonomy_runtime.schemas.runtime_event import RuntimeEvent, RuntimeEventType
from ai_autonomy_runtime.verifier.ugv_safety_validator import UGVSafetyValidator, motion_parameters


class VideoScenarioSupervisor:
    """Convert video-derived scenario fixtures into bounded UGV action proposals."""

    def __init__(self, confidence_threshold: float = 0.6) -> None:
        self.confidence_threshold = float(confidence_threshold)

    def event_from_scenario(self, scenario: Mapping[str, Any]) -> RuntimeEvent:
        perception = _scenario_perception(scenario)
        context = _mapping(scenario.get("context"))
        obstacle_detected = _bool(perception.get("obstacle_detected"))
        confidence = _float(perception.get("confidence"), 1.0 if obstacle_detected else 0.0)
        relative_position = str(perception.get("relative_position", "unknown")).lower()
        path_blocked = (
            obstacle_detected
            and confidence >= self.confidence_threshold
            and _is_path_relevant(relative_position)
        )
        event_type = RuntimeEventType.PATH_BLOCKED if path_blocked else RuntimeEventType.CAMERA_OBSERVATION
        camera_is_live = _bool(context.get("camera_is_live_on_robot"))
        payload = {
            "scenario_id": scenario.get("scenario_id", "video_scenario"),
            "video_ref": scenario.get("video_ref", ""),
            "frame_time_s": _optional_float(scenario.get("frame_time_s")),
            "path_blocked": path_blocked,
            "obstacle_detected": obstacle_detected,
            "obstacle_label": perception.get("obstacle_label", perception.get("label", "")),
            "confidence": confidence,
            "relative_position": relative_position,
            "estimated_distance_m": _optional_float(perception.get("estimated_distance_m")),
            "camera_is_live_on_robot": camera_is_live,
            "ugv_is_inverted_bench": _bool(context.get("ugv_is_inverted_bench")),
            "physical_motion_synchronized": _bool(context.get("physical_motion_synchronized")),
            "fixture_only": not camera_is_live,
            "note": (
                "external video fixture; not a synchronized robot-mounted camera stream"
                if not camera_is_live
                else "live camera context declared by scenario"
            ),
        }
        return RuntimeEvent(
            event_type=event_type,
            source="video_fixture",
            payload=payload,
            severity=Severity.WARNING if path_blocked else Severity.INFO,
            requires_model_call=False,
        )

    def propose_action(self, event: RuntimeEvent) -> ActionCandidate:
        payload = dict(event.payload)
        scenario_id = str(payload.get("scenario_id", "video_scenario"))
        path_blocked = str(event.event_type) == RuntimeEventType.PATH_BLOCKED.value
        obstacle_detected = _bool(payload.get("obstacle_detected"))
        confidence = _float(payload.get("confidence"), 0.0)
        base_parameters = {
            "duration_ms": 0,
            "linear": 0.0,
            "angular": 0.0,
            "scenario_id": scenario_id,
            "video_fixture": True,
            "camera_live_on_robot": _bool(payload.get("camera_is_live_on_robot")),
            "physical_motion_synchronized": _bool(payload.get("physical_motion_synchronized")),
            "perception_confidence": confidence,
            "perception_label": payload.get("obstacle_label", ""),
            "estimated_distance_m": payload.get("estimated_distance_m"),
            "supervisor_mode": "dry_run_only",
        }
        if path_blocked:
            return ActionCandidate(
                source="video_scenario_supervisor",
                candidate_type="ugv_motion",
                action_type="stop",
                parameters=base_parameters,
                ttl_ms=1500,
                expected_duration_ms=0,
                risk_level=RiskLevel.MEDIUM,
                requires_physical_execution=False,
                source_model="deterministic_video_scenario_supervisor",
                reason=(
                    "Video fixture indicates a path-relevant obstacle; propose STOP for "
                    "supervisor validation only. Physical execution remains disabled because "
                    "the fixture is not synchronized with the inverted UGV."
                ),
            )
        if obstacle_detected:
            reason = (
                "Video fixture contains an obstacle observation below the confidence/path relevance gate; "
                "record REPORT_ONLY and keep motion disabled."
            )
        else:
            reason = (
                "Video fixture does not indicate a blocked path; record REPORT_ONLY because this "
                "input is not synchronized with the physical UGV."
            )
        return ActionCandidate(
            source="video_scenario_supervisor",
            candidate_type="ugv_motion",
            action_type="report_only",
            parameters=base_parameters,
            ttl_ms=1500,
            expected_duration_ms=0,
            risk_level=RiskLevel.LOW,
            requires_physical_execution=False,
            source_model="deterministic_video_scenario_supervisor",
            reason=reason,
        )


def run_video_scenario_supervisor(
    scenario: Mapping[str, Any],
    output_dir: str | Path,
    confidence_threshold: float = 0.6,
    human_approved: bool = False,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    supervisor = VideoScenarioSupervisor(confidence_threshold=confidence_threshold)
    event = supervisor.event_from_scenario(scenario)
    candidate = supervisor.propose_action(event)
    verification = UGVSafetyValidator().validate(candidate, human_approved=human_approved)
    points = simulate_candidate(candidate) if verification.passed else UGV2DSimulator().path
    sim_summary = _summary_for(points)

    _write_json(output / "video_scenario.json", dict(scenario))
    _write_json(output / "runtime_event.json", event.model_dump(mode="json"))
    _write_json(output / "action_candidate.json", candidate.model_dump(mode="json"))
    _write_json(output / "verification_result.json", verification.model_dump(mode="json"))
    trajectory_csv = write_path_csv(output / "preview_trajectory.csv", points)
    preview_map = write_map_html(output / "preview_map.html", points, sim_summary)
    scenario_grid = write_scenario_grid_html(
        output / "scenario_grid.html",
        scenario=scenario,
        event=event,
        candidate=candidate,
        verification=verification.model_dump(mode="json"),
        points=points,
        sim_summary=sim_summary,
    )

    summary = {
        "accepted": verification.passed,
        "status": "dry_run_success" if verification.passed else "rejected_by_safety",
        "scenario_id": event.payload.get("scenario_id"),
        "event_type": event.event_type,
        "proposed_action": candidate.action_type,
        "reason": candidate.reason,
        "confidence_threshold": confidence_threshold,
        "output_dir": str(output),
        "runtime_event": str(output / "runtime_event.json"),
        "action_candidate": str(output / "action_candidate.json"),
        "verification_result": str(output / "verification_result.json"),
        "preview_trajectory_csv": str(trajectory_csv),
        "preview_map_html": str(preview_map),
        "scenario_grid_html": str(scenario_grid),
        "video_is_fixture": True,
        "camera_live_on_robot": bool(event.payload.get("camera_is_live_on_robot")),
        "physical_motion_synchronized": bool(event.payload.get("physical_motion_synchronized")),
        "physical_execution_connected": False,
        "requires_physical_execution": candidate.requires_physical_execution,
        "ros_published": False,
        "ssh_used": False,
        "llm_used": False,
    }
    _write_json(output / "summary.json", summary)
    return summary


def simulate_candidate(candidate: ActionCandidate) -> list[SimPoint]:
    simulator = UGV2DSimulator()
    motion = motion_parameters(candidate)
    sequence = motion.get("sequence") or []
    if sequence:
        for step in sequence:
            simulator.run_fixed(
                float(step["linear_x"]),
                float(step["angular_z"]),
                max(0.0, int(step["duration_ms"]) / 1000.0),
                dt_s=0.05,
            )
        return simulator.path
    simulator.run_fixed(
        float(motion["linear_x"]),
        float(motion["angular_z"]),
        max(0.0, int(motion["duration_ms"]) / 1000.0),
        dt_s=0.05,
    )
    return simulator.path


def write_scenario_grid_html(
    path: str | Path,
    scenario: Mapping[str, Any],
    event: RuntimeEvent,
    candidate: ActionCandidate,
    verification: Mapping[str, Any],
    points: Sequence[SimPoint],
    sim_summary: Mapping[str, Any],
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    obstacle = _obstacle_marker(event.payload)
    html = _scenario_report_html(
        scenario=scenario,
        event=event,
        candidate=candidate,
        verification_passed=bool(verification.get("passed")),
        obstacle=obstacle,
        points=points,
        sim_summary=sim_summary,
    )
    output.write_text(html, encoding="utf-8")
    return output


def _scenario_report_html(
    scenario: Mapping[str, Any],
    event: RuntimeEvent,
    candidate: ActionCandidate,
    verification_passed: bool,
    obstacle: Mapping[str, Any],
    points: Sequence[SimPoint],
    sim_summary: Mapping[str, Any],
) -> str:
    payload = event.payload
    event_type = str(event.event_type)
    action_type = str(candidate.action_type)
    status_text = "dry-run success" if verification_passed else "blocked"
    status_class = "badge" if verification_passed else "badge warn"
    distance = f"{float(obstacle.get('estimated_distance_m') or 0.0):.2f} m" if obstacle.get("detected") else "none"
    trajectory = f"{float(sim_summary.get('path_distance_m') or 0.0):.3f} m"
    svg = _scenario_svg(points, obstacle, action_type)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>UGV Video Scenario Supervisor</title>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; min-height: 100%; }}
    body {{ font-family: Arial, Helvetica, sans-serif; background: #f5f7fa; color: #142033; }}
    header {{ display: flex; justify-content: space-between; gap: 16px; padding: 18px 24px; background: #fff; border-bottom: 1px solid #d8e0eb; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; letter-spacing: 0; }}
    .subtitle {{ margin: 0; color: #657286; font-size: 14px; }}
    .badge {{ align-self: start; padding: 7px 10px; border-radius: 6px; border: 1px solid #cfe7dc; background: #e8f6ef; color: #047857; font-weight: 700; font-size: 13px; white-space: nowrap; }}
    .warn {{ border-color: #fed7aa; background: #fff7ed; color: #9a3412; }}
    .metrics {{ display: grid; grid-template-columns: repeat(5, minmax(130px, 1fr)); gap: 10px; padding: 14px 24px; }}
    .metric {{ min-height: 72px; padding: 12px 14px; background: #fff; border: 1px solid #d8e0eb; border-radius: 6px; }}
    .metric span {{ display: block; color: #657286; font-size: 12px; margin-bottom: 8px; }}
    .metric strong {{ display: block; font-size: 19px; overflow-wrap: anywhere; }}
    main {{ display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; padding: 0 24px 24px; }}
    .mapPanel, .side {{ background: #fff; border: 1px solid #d8e0eb; border-radius: 6px; overflow: hidden; }}
    .panelTitle {{ display: flex; justify-content: space-between; padding: 12px 14px; border-bottom: 1px solid #d8e0eb; color: #657286; font-size: 13px; }}
    svg {{ display: block; width: 100%; height: auto; background: #fbfcfe; }}
    .legend {{ display: flex; gap: 14px; padding: 10px 14px; border-top: 1px solid #d8e0eb; color: #657286; font-size: 12px; }}
    .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; vertical-align: -1px; }}
    .robotDot {{ background: #1f2a44; }} .pathDot {{ background: #0f766e; }} .obsDot {{ background: #d14d28; }}
    .side {{ padding: 14px; display: grid; align-content: start; gap: 12px; }}
    .section {{ border-bottom: 1px solid #d8e0eb; padding-bottom: 12px; }}
    .section:last-child {{ border-bottom: 0; padding-bottom: 0; }}
    h2 {{ margin: 0 0 8px; font-size: 14px; letter-spacing: 0; }}
    dl {{ display: grid; grid-template-columns: 116px 1fr; gap: 7px 10px; margin: 0; font-size: 13px; }}
    dt {{ color: #657286; }} dd {{ margin: 0; overflow-wrap: anywhere; }}
    .reason {{ margin: 0; color: #657286; font-size: 13px; line-height: 1.45; }}
    @media (max-width: 980px) {{
      header {{ padding: 14px; }}
      h1 {{ font-size: 20px; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); padding: 12px 14px; }}
      main {{ grid-template-columns: 1fr; padding: 0 14px 14px; }}
    }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>UGV Video Scenario Supervisor</h1>
      <p class="subtitle">{_e(payload.get("note", "video fixture dry-run"))}</p>
    </div>
    <span class="{status_class}">{status_text}</span>
  </header>
  <section class="metrics">
    <div class="metric"><span>Event</span><strong>{_e(event_type)}</strong></div>
    <div class="metric"><span>Proposed action</span><strong>{_e(action_type)}</strong></div>
    <div class="metric"><span>Confidence</span><strong>{float(obstacle.get("confidence") or 0.0):.2f}</strong></div>
    <div class="metric"><span>Distance</span><strong>{_e(distance)}</strong></div>
    <div class="metric"><span>Trajectory</span><strong>{_e(trajectory)}</strong></div>
  </section>
  <main>
    <section class="mapPanel">
      <div class="panelTitle"><span>Scenario grid and dry-run trajectory</span><span>{'synchronized' if payload.get('physical_motion_synchronized') else 'fixture only'}</span></div>
      {svg}
      <div class="legend">
        <span><i class="dot robotDot"></i>UGV bench pose</span>
        <span><i class="dot pathDot"></i>dry-run trajectory</span>
        <span><i class="dot obsDot"></i>video obstacle</span>
      </div>
    </section>
    <aside class="side">
      <section class="section">
        <h2>Scenario</h2>
        <dl>
          <dt>ID</dt><dd>{_e(payload.get("scenario_id") or scenario.get("scenario_id") or "-")}</dd>
          <dt>Video</dt><dd>{_e(payload.get("video_ref") or scenario.get("video_ref") or "-")}</dd>
          <dt>Frame time</dt><dd>{_frame_time(payload.get("frame_time_s"))}</dd>
          <dt>Fixture only</dt><dd>{_yn(payload.get("fixture_only"))}</dd>
        </dl>
      </section>
      <section class="section">
        <h2>Safety</h2>
        <dl>
          <dt>Validation</dt><dd>{'passed' if verification_passed else 'blocked'}</dd>
          <dt>ROS publish</dt><dd>false</dd>
          <dt>SSH used</dt><dd>false</dd>
          <dt>Physical exec</dt><dd>{_yn(candidate.requires_physical_execution)}</dd>
        </dl>
      </section>
      <section class="section">
        <h2>Reason</h2>
        <p class="reason">{_e(candidate.reason or "-")}</p>
      </section>
    </aside>
  </main>
</body>
</html>
"""


def _scenario_svg(points: Sequence[SimPoint], obstacle: Mapping[str, Any], action_type: str) -> str:
    width, height, pad = 980.0, 640.0, 56.0
    bounds = _svg_bounds(points, obstacle, width, height, pad)

    def project(x_m: float, y_m: float) -> tuple[float, float]:
        scale = min((width - 2 * pad) / (bounds["max_x"] - bounds["min_x"]), (height - 2 * pad) / (bounds["max_y"] - bounds["min_y"]))
        return pad + (x_m - bounds["min_x"]) * scale, height - pad - (y_m - bounds["min_y"]) * scale

    elements = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_n(width)} {_n(height)}" role="img" aria-label="UGV scenario grid">',
        '<rect width="100%" height="100%" fill="#fbfcfe"/>',
    ]
    _append_grid(elements, bounds, project, width, height, pad)
    ox, oy = project(0.0, 0.0)
    lx, ly = project(2.4, 1.15)
    rx, ry = project(2.4, -1.15)
    elements.append(
        f'<polygon points="{_n(ox)},{_n(oy)} {_n(lx)},{_n(ly)} {_n(rx)},{_n(ry)}" '
        'fill="rgba(37,99,235,0.08)" stroke="rgba(37,99,235,0.22)" stroke-width="1.5"/>'
    )
    if points:
        polyline = " ".join(f"{_n(x)},{_n(y)}" for x, y in (project(point.x_m, point.y_m) for point in points))
        elements.append(f'<polyline points="{polyline}" fill="none" stroke="#0f766e" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>')
        sx, sy = project(points[0].x_m, points[0].y_m)
        ex, ey = project(points[-1].x_m, points[-1].y_m)
        elements.append(f'<circle cx="{_n(sx)}" cy="{_n(sy)}" r="6" fill="#2563eb"/>')
        elements.append(f'<circle cx="{_n(ex)}" cy="{_n(ey)}" r="8" fill="#0f766e"/>')
    if action_type == "stop":
        elements.append(f'<circle cx="{_n(ox)}" cy="{_n(oy)}" r="34" fill="rgba(209,77,40,0.08)" stroke="#d14d28" stroke-width="3"/>')
        elements.append(f'<text x="{_n(ox - 16)}" y="{_n(oy - 40)}" font-family="Arial" font-size="12" font-weight="700" fill="#9a3412">STOP</text>')
    if obstacle.get("detected"):
        px, py = project(float(obstacle.get("x_m") or 0.0), float(obstacle.get("y_m") or 0.0))
        fill = "#d14d28" if obstacle.get("path_blocked") else "#ca8a04"
        elements.append(f'<circle cx="{_n(px)}" cy="{_n(py)}" r="17" fill="{fill}" stroke="#ffffff" stroke-width="3"/>')
        elements.append(f'<text x="{_n(px + 22)}" y="{_n(py + 4)}" font-family="Arial" font-size="13" fill="#142033">{_e(obstacle.get("label") or "obstacle")}</text>')
    elements.append(f'<polygon points="{_n(ox + 24)},{_n(oy)} {_n(ox - 16)},{_n(oy - 12)} {_n(ox - 16)},{_n(oy + 12)}" fill="#1f2a44"/>')
    elements.append('<text x="14" y="22" font-family="Arial" font-size="12" fill="#657286">UGV inverted bench pose at origin</text>')
    elements.append(f'<text x="{_n(width - 142)}" y="42" font-family="Arial" font-size="12" fill="#657286">+x video forward</text>')
    elements.append("</svg>")
    return "".join(elements)


def _svg_bounds(points: Sequence[SimPoint], obstacle: Mapping[str, Any], width: float, height: float, pad: float) -> dict[str, float]:
    coords = [(0.0, 0.0), (2.4, 1.15), (2.4, -1.15)]
    coords.extend((point.x_m, point.y_m) for point in points)
    if obstacle.get("detected"):
        coords.append((float(obstacle.get("x_m") or 0.0), float(obstacle.get("y_m") or 0.0)))
    xs, ys = [x for x, _ in coords], [y for _, y in coords]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 2.0)
    span_y = max(max_y - min_y, 1.5)
    aspect = (width - 2 * pad) / (height - 2 * pad)
    if span_x / span_y < aspect:
        span_x = span_y * aspect
    else:
        span_y = span_x / aspect
    cx, cy = (min_x + max_x) / 2, (min_y + max_y) / 2
    span_x *= 1.18
    span_y *= 1.18
    return {"min_x": cx - span_x / 2, "max_x": cx + span_x / 2, "min_y": cy - span_y / 2, "max_y": cy + span_y / 2}


def _append_grid(
    elements: list[str],
    bounds: Mapping[str, float],
    project: Any,
    width: float,
    height: float,
    pad: float,
) -> None:
    step = _choose_step(max(bounds["max_x"] - bounds["min_x"], bounds["max_y"] - bounds["min_y"]) / 8)
    x = math.ceil(bounds["min_x"] / step) * step
    while x <= bounds["max_x"] + 1e-9:
        px, _ = project(x, 0.0)
        elements.append(f'<line x1="{_n(px)}" y1="{_n(pad * 0.55)}" x2="{_n(px)}" y2="{_n(height - pad * 0.55)}" stroke="#d8e0eb" stroke-width="1"/>')
        elements.append(f'<text x="{_n(px + 3)}" y="{_n(height - 16)}" font-family="Arial" font-size="12" fill="#657286">{x:.1f}</text>')
        x += step
    y = math.ceil(bounds["min_y"] / step) * step
    while y <= bounds["max_y"] + 1e-9:
        _, py = project(0.0, y)
        elements.append(f'<line x1="{_n(pad * 0.55)}" y1="{_n(py)}" x2="{_n(width - pad * 0.55)}" y2="{_n(py)}" stroke="#d8e0eb" stroke-width="1"/>')
        elements.append(f'<text x="8" y="{_n(py - 4)}" font-family="Arial" font-size="12" fill="#657286">{y:.1f}</text>')
        y += step
    ox, oy = project(0.0, 0.0)
    elements.append(f'<line x1="{_n(pad * 0.55)}" y1="{_n(oy)}" x2="{_n(width - pad * 0.55)}" y2="{_n(oy)}" stroke="#8b98aa" stroke-width="1.2"/>')
    elements.append(f'<line x1="{_n(ox)}" y1="{_n(pad * 0.55)}" x2="{_n(ox)}" y2="{_n(height - pad * 0.55)}" stroke="#8b98aa" stroke-width="1.2"/>')


def _summary_for(points: Sequence[SimPoint]) -> dict[str, float | int]:
    simulator = UGV2DSimulator()
    simulator.path = list(points)
    if points:
        simulator.pose.t_s = points[-1].t_s
        simulator.pose.x_m = points[-1].x_m
        simulator.pose.y_m = points[-1].y_m
        simulator.pose.yaw_rad = points[-1].yaw_rad
    return simulator.summary()


def _obstacle_marker(payload: Mapping[str, Any]) -> dict[str, Any]:
    distance = _optional_float(payload.get("estimated_distance_m")) or 1.5
    distance = max(0.25, min(distance, 6.0))
    position = str(payload.get("relative_position", "front")).lower()
    if position in {"left", "port"}:
        x_m, y_m = 0.0, distance
    elif position in {"right", "starboard"}:
        x_m, y_m = 0.0, -distance
    elif position in {"rear", "behind"}:
        x_m, y_m = -distance, 0.0
    elif position in {"front_left", "ahead_left"}:
        x_m, y_m = distance / math.sqrt(2), distance / math.sqrt(2)
    elif position in {"front_right", "ahead_right"}:
        x_m, y_m = distance / math.sqrt(2), -distance / math.sqrt(2)
    else:
        x_m, y_m = distance, 0.0
    return {
        "x_m": x_m,
        "y_m": y_m,
        "label": payload.get("obstacle_label") or "obstacle",
        "confidence": _float(payload.get("confidence"), 0.0),
        "detected": _bool(payload.get("obstacle_detected")),
        "path_blocked": _bool(payload.get("path_blocked")),
        "relative_position": position,
        "estimated_distance_m": distance,
    }


def _scenario_perception(scenario: Mapping[str, Any]) -> Mapping[str, Any]:
    perception = scenario.get("perception")
    if isinstance(perception, Mapping):
        return perception
    observations = scenario.get("observations")
    if isinstance(observations, list) and observations:
        first = observations[0]
        if isinstance(first, Mapping):
            return first
    return {}


def _choose_step(raw: float) -> float:
    magnitude = 10 ** math.floor(math.log10(max(raw, 0.001)))
    normalized = raw / magnitude
    if normalized < 1.5:
        return magnitude
    if normalized < 3.5:
        return 2 * magnitude
    if normalized < 7.5:
        return 5 * magnitude
    return 10 * magnitude


def _is_path_relevant(position: str) -> bool:
    return position not in {"left", "right", "rear", "behind"}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _frame_time(value: Any) -> str:
    numeric = _optional_float(value)
    return "-" if numeric is None else f"{numeric:.2f} s"


def _yn(value: Any) -> str:
    return "true" if bool(value) else "false"


def _n(value: float) -> str:
    return f"{value:.2f}"


def _e(value: Any) -> str:
    return escape(str(value), quote=True)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

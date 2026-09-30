from __future__ import annotations

import csv
import json
import math
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from ai_autonomy_runtime.sandbox.ugv_2d_simulator import SimPoint, write_map_html, write_path_csv

STATE_PREFIX = "UGV_STATE_JSON "
EVENT_PREFIX = "UGV_EVENT_JSON "


@dataclass
class ParsedTelemetry:
    kind: Literal["state", "event", "ignored", "malformed"]
    payload: dict[str, Any] | None = None
    raw_line: str = ""
    error: str | None = None


def parse_telemetry_line(line: str) -> ParsedTelemetry:
    raw = line.rstrip("\r\n")
    if raw.startswith(STATE_PREFIX):
        return _parse_prefixed_json(raw, STATE_PREFIX, "state")
    if raw.startswith(EVENT_PREFIX):
        return _parse_prefixed_json(raw, EVENT_PREFIX, "event")
    return ParsedTelemetry(kind="ignored", raw_line=raw)


def _parse_prefixed_json(raw: str, prefix: str, kind: Literal["state", "event"]) -> ParsedTelemetry:
    body = raw[len(prefix) :]
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        return ParsedTelemetry(kind="malformed", raw_line=raw, error=str(exc))
    if not isinstance(payload, dict):
        return ParsedTelemetry(kind="malformed", raw_line=raw, error="telemetry payload must be a JSON object")
    return ParsedTelemetry(kind=kind, payload=payload, raw_line=raw)


class LiveStateStore:
    def __init__(self, run_id: str, output_dir: str | Path, stale_after_s: float = 2.0) -> None:
        self.run_id = run_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.stale_after_s = float(stale_after_s)
        self.samples: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self.trajectory: list[SimPoint] = []
        self.first_wall_time: float | None = None
        self.last_sample_monotonic: float | None = None
        self.last_update_wall_time: float | None = None
        self.stream_complete = False
        self._last_csv_warning: str | None = None
        self._write_live_map_html()
        self.export_trajectory_csv()
        self.write_live_state()

    @property
    def sample_count(self) -> int:
        with self._lock:
            return len(self.samples)

    def apply_state(self, payload: dict[str, Any]) -> None:
        with self._lock:
            now = time.monotonic()
            wall_time = _float_or_none(payload.get("wall_time")) or time.time()
            if self.first_wall_time is None:
                self.first_wall_time = wall_time
            self.samples.append(payload)
            self.last_sample_monotonic = now
            self.last_update_wall_time = time.time()
            point = self._point_from_state(payload, wall_time)
            if point is not None:
                self.trajectory.append(point)
            self._append_jsonl(self.output_dir / "telemetry.jsonl", payload)
            self.export_trajectory_csv()
            self.write_live_state()

    def add_event(self, payload: dict[str, Any]) -> None:
        with self._lock:
            event = {"time": time.time(), **payload}
            self.events.append(event)
            self._append_jsonl(self.output_dir / "events.jsonl", event)
            self.write_live_state()

    def add_malformed_line(self, raw_line: str, error: str | None) -> None:
        self.add_event(
            {
                "event_type": "malformed_telemetry",
                "severity": "warning",
                "error": error or "unknown parser error",
                "line": raw_line,
            }
        )

    def mark_stream_disconnected(self, reason: str) -> None:
        self.add_event({"event_type": "ssh_stream_disconnected", "severity": "warning", "reason": reason})

    def mark_complete(self, reason: str = "duration_elapsed") -> None:
        with self._lock:
            self.stream_complete = True
        self.add_event({"event_type": "stream_complete", "severity": "info", "reason": reason})
        self.write_final_artifacts()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            stale = self._is_stale()
            if not self.samples:
                return {
                    "run_id": self.run_id,
                    "sample_count": 0,
                    "status": "waiting",
                    "stale": True,
                    "last_state": None,
                    "message": "waiting for Jetson telemetry",
                    "trajectory": [],
                    "events": self.events[-20:],
                }
            status = "complete" if self.stream_complete else ("stale" if stale else "live")
            return {
                "run_id": self.run_id,
                "sample_count": len(self.samples),
                "status": status,
                "stale": stale,
                "last_update_wall_time": self.last_update_wall_time,
                "last_state": self.samples[-1],
                "message": "telemetry stale" if stale and not self.stream_complete else "ok",
                "trajectory": [asdict(point) for point in _sample_points(self.trajectory, 1200)],
                "summary": self._summary(),
                "events": self.events[-20:],
            }

    def write_live_state(self) -> Path:
        with self._lock:
            path = self.output_dir / "live_state.json"
            _atomic_write_json(path, self.snapshot())
            return path

    def export_trajectory_csv(self) -> Path | None:
        with self._lock:
            path = self.output_dir / "trajectory.csv"
            try:
                if self.trajectory:
                    return write_path_csv(path, self.trajectory)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(
                        handle,
                        fieldnames=["t_s", "x_m", "y_m", "yaw_rad", "yaw_deg", "linear_x", "angular_z", "source"],
                    )
                    writer.writeheader()
                return path
            except OSError as exc:
                message = str(exc)
                if message != self._last_csv_warning:
                    self._last_csv_warning = message
                    print(f"Warning: could not write trajectory.csv: {message}", flush=True)
                return None

    def write_final_artifacts(self) -> dict[str, str | None]:
        with self._lock:
            trajectory_csv = self.export_trajectory_csv()
            map_html = None
            try:
                map_html = write_map_html(self.output_dir / "map.html", self.trajectory, self._summary())
            except OSError as exc:
                self.add_event({"event_type": "map_write_failed", "severity": "warning", "error": str(exc)})
            summary = {
                "run_id": self.run_id,
                "run_dir": str(self.output_dir),
                "sample_count": len(self.samples),
                "events_count": len(self.events),
                "trajectory_csv": str(trajectory_csv) if trajectory_csv else None,
                "map_html": str(map_html) if map_html else None,
                "stream_complete": self.stream_complete,
                "simulation": self._summary(),
            }
            _atomic_write_json(self.output_dir / "summary.json", summary)
            self.write_live_state()
            return {
                "trajectory_csv": str(trajectory_csv) if trajectory_csv else None,
                "map_html": str(map_html) if map_html else None,
                "summary_json": str(self.output_dir / "summary.json"),
            }

    def _point_from_state(self, payload: dict[str, Any], wall_time: float) -> SimPoint | None:
        pose = payload.get("pose")
        if not isinstance(pose, dict):
            return None
        x_m = _float_or_none(pose.get("x"))
        y_m = _float_or_none(pose.get("y"))
        yaw_rad = _float_or_none(pose.get("yaw"))
        if x_m is None or y_m is None or yaw_rad is None:
            return None
        velocity = payload.get("velocity") if isinstance(payload.get("velocity"), dict) else {}
        cmd_out = payload.get("cmd_out") if isinstance(payload.get("cmd_out"), dict) else {}
        cmd_in = payload.get("cmd_in") if isinstance(payload.get("cmd_in"), dict) else {}
        linear_x = _first_float(velocity.get("linear_x"), cmd_out.get("linear_x"), cmd_in.get("linear_x"), 0.0)
        angular_z = _first_float(velocity.get("angular_z"), cmd_out.get("angular_z"), cmd_in.get("angular_z"), 0.0)
        t_s = max(0.0, wall_time - (self.first_wall_time or wall_time))
        return SimPoint(
            t_s=t_s,
            x_m=x_m,
            y_m=y_m,
            yaw_rad=yaw_rad,
            linear_x=linear_x,
            angular_z=angular_z,
            source=str(payload.get("source_pose_topic") or "pose"),
        )

    def _is_stale(self) -> bool:
        if self.last_sample_monotonic is None:
            return True
        if self.stream_complete:
            return False
        return (time.monotonic() - self.last_sample_monotonic) > self.stale_after_s

    def _summary(self) -> dict[str, float | int]:
        if not self.trajectory:
            return {
                "samples": 0,
                "duration_s": 0.0,
                "final_x_m": 0.0,
                "final_y_m": 0.0,
                "final_yaw_rad": 0.0,
                "final_yaw_deg": 0.0,
                "path_distance_m": 0.0,
            }
        distance_m = 0.0
        for previous, current in zip(self.trajectory, self.trajectory[1:]):
            distance_m += math.hypot(current.x_m - previous.x_m, current.y_m - previous.y_m)
        final = self.trajectory[-1]
        return {
            "samples": len(self.trajectory),
            "duration_s": final.t_s - self.trajectory[0].t_s,
            "final_x_m": final.x_m,
            "final_y_m": final.y_m,
            "final_yaw_rad": final.yaw_rad,
            "final_yaw_deg": math.degrees(final.yaw_rad),
            "path_distance_m": distance_m,
        }

    def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        except OSError as exc:
            print(f"Warning: could not append {path.name}: {exc}", flush=True)

    def _write_live_map_html(self) -> Path:
        path = self.output_dir / "live_map.html"
        path.write_text(live_map_html(), encoding="utf-8")
        return path


def live_map_html(refresh_ms: int = 300) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>UGV Live Observation</title>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ height: 100%; margin: 0; }}
    body {{ font-family: Arial, Helvetica, sans-serif; color: #182033; background: #f5f7fa; overflow: hidden; }}
    .app {{ height: 100%; display: grid; grid-template-columns: 320px 1fr; }}
    aside {{ background: #ffffff; border-right: 1px solid #dce3ec; padding: 16px; overflow: auto; }}
    main {{ position: relative; min-width: 0; min-height: 0; }}
    canvas {{ width: 100%; height: 100%; display: block; background: #fbfcfe; }}
    h1 {{ margin: 0 0 14px; font-size: 18px; line-height: 1.2; }}
    .status {{ display: inline-flex; align-items: center; min-height: 26px; padding: 3px 8px; border-radius: 6px; font-size: 13px; font-weight: 700; background: #e7f5ef; color: #047857; }}
    .status.waiting {{ background: #eef2f7; color: #526071; }}
    .status.stale {{ background: #fff3d9; color: #9a5a00; }}
    .status.complete {{ background: #e8efff; color: #1d4ed8; }}
    .warning {{ display: none; margin: 12px 0; padding: 10px; border: 1px solid #f4c56a; border-radius: 6px; background: #fff8e6; color: #7a4a00; font-size: 13px; line-height: 1.35; }}
    .warning.visible {{ display: block; }}
    dl {{ display: grid; grid-template-columns: 120px 1fr; gap: 8px 10px; margin: 16px 0; font-size: 13px; }}
    dt {{ color: #667085; }}
    dd {{ margin: 0; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }}
    .section {{ border-top: 1px solid #e4e9f0; padding-top: 12px; margin-top: 12px; }}
    .legend {{ position: absolute; left: 14px; bottom: 14px; background: rgba(255,255,255,.94); border: 1px solid #dce3ec; border-radius: 6px; padding: 8px 10px; color: #667085; font-size: 12px; }}
    .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; vertical-align: -1px; }}
    .start {{ background: #1d4ed8; }}
    .path {{ background: #067a6f; }}
    .current {{ background: #be123c; }}
    @media (max-width: 820px) {{
      body {{ overflow: auto; }}
      .app {{ min-height: 100%; height: auto; grid-template-columns: 1fr; grid-template-rows: auto 62vh; }}
      aside {{ border-right: 0; border-bottom: 1px solid #dce3ec; }}
    }}
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <h1>UGV Live Observation</h1>
      <div id="status" class="status waiting">waiting</div>
      <div id="warning" class="warning">Telemetry is stale. The last known trajectory remains visible.</div>
      <dl>
        <dt>run_id</dt><dd id="runId">-</dd>
        <dt>samples</dt><dd id="samples">0</dd>
        <dt>last update</dt><dd id="lastUpdate">-</dd>
        <dt>stale</dt><dd id="stale">true</dd>
      </dl>
      <div class="section">
        <dl>
          <dt>x</dt><dd id="x">-</dd>
          <dt>y</dt><dd id="y">-</dd>
          <dt>yaw</dt><dd id="yaw">-</dd>
          <dt>distance</dt><dd id="distance">0.000 m</dd>
        </dl>
      </div>
      <div class="section">
        <dl>
          <dt>cmd_in</dt><dd id="cmdIn">-</dd>
          <dt>cmd_out</dt><dd id="cmdOut">-</dd>
          <dt>ROS</dt><dd id="ros">-</dd>
          <dt>odom</dt><dd id="odom">-</dd>
        </dl>
      </div>
    </aside>
    <main>
      <canvas id="map"></canvas>
      <div class="legend">
        <span><i class="dot start"></i>start</span>
        <span><i class="dot path"></i>path</span>
        <span><i class="dot current"></i>current</span>
      </div>
    </main>
  </div>
  <script>
    const refreshMs = {refresh_ms};
    const canvas = document.getElementById("map");
    const ctx = canvas.getContext("2d");
    const els = {{
      status: document.getElementById("status"),
      warning: document.getElementById("warning"),
      runId: document.getElementById("runId"),
      samples: document.getElementById("samples"),
      lastUpdate: document.getElementById("lastUpdate"),
      stale: document.getElementById("stale"),
      x: document.getElementById("x"),
      y: document.getElementById("y"),
      yaw: document.getElementById("yaw"),
      distance: document.getElementById("distance"),
      cmdIn: document.getElementById("cmdIn"),
      cmdOut: document.getElementById("cmdOut"),
      ros: document.getElementById("ros"),
      odom: document.getElementById("odom"),
    }};
    let payload = {{ trajectory: [], last_state: null, sample_count: 0, status: "waiting", stale: true }};

    function resize() {{
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * ratio));
      canvas.height = Math.max(1, Math.floor(rect.height * ratio));
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      draw();
    }}

    async function poll() {{
      try {{
        const res = await fetch("/live_state.json?ts=" + Date.now(), {{ cache: "no-store" }});
        if (res.ok) payload = await res.json();
      }} catch (error) {{
        payload = {{ ...payload, stale: true, status: payload.sample_count ? "stale" : "waiting" }};
      }}
      updatePanel();
      draw();
    }}

    function updatePanel() {{
      const state = payload.last_state || null;
      const pose = state && state.pose ? state.pose : null;
      const summary = payload.summary || {{}};
      els.status.textContent = payload.status || "waiting";
      els.status.className = "status " + (payload.status || "waiting");
      els.warning.className = payload.stale && payload.sample_count > 0 ? "warning visible" : "warning";
      els.runId.textContent = payload.run_id || "-";
      els.samples.textContent = String(payload.sample_count || 0);
      els.lastUpdate.textContent = payload.last_update_wall_time ? new Date(payload.last_update_wall_time * 1000).toLocaleTimeString() : "-";
      els.stale.textContent = String(Boolean(payload.stale));
      els.x.textContent = pose ? Number(pose.x || 0).toFixed(3) + " m" : "-";
      els.y.textContent = pose ? Number(pose.y || 0).toFixed(3) + " m" : "-";
      els.yaw.textContent = pose ? (Number(pose.yaw || 0) * 180 / Math.PI).toFixed(1) + " deg" : "-";
      els.distance.textContent = Number(summary.path_distance_m || 0).toFixed(3) + " m";
      els.cmdIn.textContent = formatTwist(state && state.cmd_in);
      els.cmdOut.textContent = formatTwist(state && state.cmd_out);
      const status = state && state.status ? state.status : {{}};
      els.ros.textContent = status.ros_connected === undefined ? "-" : String(status.ros_connected);
      els.odom.textContent = status.odom_available === undefined ? "-" : String(status.odom_available);
    }}

    function formatTwist(twist) {{
      if (!twist) return "-";
      return "v=" + Number(twist.linear_x || 0).toFixed(3) + ", w=" + Number(twist.angular_z || 0).toFixed(3);
    }}

    function draw() {{
      const rect = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, rect.width, rect.height);
      ctx.fillStyle = "#fbfcfe";
      ctx.fillRect(0, 0, rect.width, rect.height);
      const points = payload.trajectory || [];
      const b = bounds(points);
      const pad = 42;
      const scale = Math.min((rect.width - pad * 2) / (b.maxX - b.minX), (rect.height - pad * 2) / (b.maxY - b.minY));
      const project = p => ({{ x: pad + (p.x_m - b.minX) * scale, y: rect.height - pad - (p.y_m - b.minY) * scale }});
      drawGrid(rect, b, project);
      if (points.length > 1) {{
        ctx.strokeStyle = "#067a6f";
        ctx.lineWidth = 4;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.beginPath();
        points.forEach((p, i) => {{
          const q = project(p);
          if (i === 0) ctx.moveTo(q.x, q.y);
          else ctx.lineTo(q.x, q.y);
        }});
        ctx.stroke();
      }}
      if (points.length) {{
        const start = project(points[0]);
        const currentPoint = points[points.length - 1];
        const current = project(currentPoint);
        ctx.fillStyle = "#1d4ed8";
        ctx.beginPath();
        ctx.arc(start.x, start.y, 6, 0, Math.PI * 2);
        ctx.fill();
        drawRobot(current, currentPoint.yaw_rad || 0);
      }}
    }}

    function bounds(points) {{
      if (!points.length) return {{ minX: -2, maxX: 2, minY: -2, maxY: 2 }};
      const xs = points.map(p => Number(p.x_m || 0));
      const ys = points.map(p => Number(p.y_m || 0));
      let minX = Math.min(...xs), maxX = Math.max(...xs);
      let minY = Math.min(...ys), maxY = Math.max(...ys);
      const span = Math.max(maxX - minX, maxY - minY, 0.5);
      const cx = (minX + maxX) / 2;
      const cy = (minY + maxY) / 2;
      const pad = span * 0.28 + 0.3;
      return {{ minX: cx - span / 2 - pad, maxX: cx + span / 2 + pad, minY: cy - span / 2 - pad, maxY: cy + span / 2 + pad }};
    }}

    function drawGrid(rect, b, project) {{
      const step = chooseStep(Math.max(b.maxX - b.minX, b.maxY - b.minY) / 8);
      ctx.strokeStyle = "#d7dde6";
      ctx.lineWidth = 1;
      for (let gx = Math.ceil(b.minX / step) * step; gx <= b.maxX; gx += step) {{
        const p = project({{ x_m: gx, y_m: b.minY }});
        ctx.beginPath(); ctx.moveTo(p.x, 30); ctx.lineTo(p.x, rect.height - 30); ctx.stroke();
      }}
      for (let gy = Math.ceil(b.minY / step) * step; gy <= b.maxY; gy += step) {{
        const p = project({{ x_m: b.minX, y_m: gy }});
        ctx.beginPath(); ctx.moveTo(30, p.y); ctx.lineTo(rect.width - 30, p.y); ctx.stroke();
      }}
    }}

    function chooseStep(raw) {{
      const pow = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 0.001))));
      const norm = raw / pow;
      if (norm < 1.5) return pow;
      if (norm < 3.5) return 2 * pow;
      if (norm < 7.5) return 5 * pow;
      return 10 * pow;
    }}

    function drawRobot(q, yaw) {{
      ctx.save();
      ctx.translate(q.x, q.y);
      ctx.rotate(-yaw);
      ctx.fillStyle = "#be123c";
      ctx.beginPath();
      ctx.moveTo(18, 0);
      ctx.lineTo(-12, -9);
      ctx.lineTo(-12, 9);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }}

    window.addEventListener("resize", resize);
    resize();
    poll();
    setInterval(poll, refreshMs);
  </script>
</body>
</html>
"""


def _sample_points(points: list[SimPoint], max_points: int) -> list[SimPoint]:
    if max_points <= 0 or len(points) <= max_points:
        return list(points)
    step = max(1, math.ceil(len(points) / max_points))
    sampled = list(points[::step])
    if sampled[-1] is not points[-1]:
        sampled.append(points[-1])
    return sampled


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{threading.get_ident()}.{time.time_ns()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        for attempt in range(6):
            try:
                temp.replace(path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.02 * (attempt + 1))
    finally:
        if temp.exists():
            temp.unlink()


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_float(*values: Any) -> float:
    for value in values:
        parsed = _float_or_none(value)
        if parsed is not None:
            return parsed
    return 0.0

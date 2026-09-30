from __future__ import annotations

import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass
class TwistSample:
    t_s: float
    linear_x: float
    angular_z: float
    source: str = "command"


@dataclass
class Pose2D:
    t_s: float = 0.0
    x_m: float = 0.0
    y_m: float = 0.0
    yaw_rad: float = 0.0


@dataclass
class SimPoint:
    t_s: float
    x_m: float
    y_m: float
    yaw_rad: float
    linear_x: float
    angular_z: float
    source: str


class UGV2DSimulator:
    """Small kinematic simulator for low-speed Jackal command validation."""

    def __init__(self, initial_pose: Pose2D | None = None) -> None:
        self.pose = initial_pose or Pose2D()
        self.path: list[SimPoint] = [
            SimPoint(
                t_s=self.pose.t_s,
                x_m=self.pose.x_m,
                y_m=self.pose.y_m,
                yaw_rad=self.pose.yaw_rad,
                linear_x=0.0,
                angular_z=0.0,
                source="initial",
            )
        ]

    def step(self, linear_x: float, angular_z: float, dt_s: float, source: str = "command") -> SimPoint:
        dt_s = max(0.0, float(dt_s))
        yaw_mid = self.pose.yaw_rad + 0.5 * angular_z * dt_s
        self.pose.x_m += linear_x * math.cos(yaw_mid) * dt_s
        self.pose.y_m += linear_x * math.sin(yaw_mid) * dt_s
        self.pose.yaw_rad = normalize_angle(self.pose.yaw_rad + angular_z * dt_s)
        self.pose.t_s += dt_s
        point = SimPoint(
            t_s=self.pose.t_s,
            x_m=self.pose.x_m,
            y_m=self.pose.y_m,
            yaw_rad=self.pose.yaw_rad,
            linear_x=linear_x,
            angular_z=angular_z,
            source=source,
        )
        self.path.append(point)
        return point

    def run_fixed(self, linear_x: float, angular_z: float, duration_s: float, dt_s: float = 0.05) -> list[SimPoint]:
        remaining = max(0.0, duration_s)
        while remaining > 1e-9:
            step_dt = min(dt_s, remaining)
            self.step(linear_x, angular_z, step_dt, source="fixed")
            remaining -= step_dt
        return self.path

    def run_samples(self, samples: Sequence[TwistSample]) -> list[SimPoint]:
        if not samples:
            return self.path
        sorted_samples = sorted(samples, key=lambda sample: sample.t_s)
        self.pose.t_s = sorted_samples[0].t_s
        self.path[0].t_s = self.pose.t_s
        for index, sample in enumerate(sorted_samples):
            if index + 1 < len(sorted_samples):
                dt_s = sorted_samples[index + 1].t_s - sample.t_s
            else:
                dt_s = 0.0
            self.step(sample.linear_x, sample.angular_z, dt_s, source=sample.source)
        return self.path

    def summary(self) -> dict[str, float | int]:
        distance_m = 0.0
        for previous, current in zip(self.path, self.path[1:]):
            distance_m += math.hypot(current.x_m - previous.x_m, current.y_m - previous.y_m)
        final = self.path[-1]
        return {
            "samples": len(self.path),
            "duration_s": final.t_s - self.path[0].t_s if self.path else 0.0,
            "final_x_m": final.x_m,
            "final_y_m": final.y_m,
            "final_yaw_rad": final.yaw_rad,
            "final_yaw_deg": math.degrees(final.yaw_rad),
            "path_distance_m": distance_m,
        }


def command_to_twist(command: str, linear: float, angular: float) -> tuple[float, float]:
    if command == "forward":
        return abs(linear), 0.0
    if command == "back":
        return -abs(linear), 0.0
    if command == "left":
        return 0.0, abs(angular)
    if command == "right":
        return 0.0, -abs(angular)
    return 0.0, 0.0


def normalize_angle(angle_rad: float) -> float:
    return math.atan2(math.sin(angle_rad), math.cos(angle_rad))


def load_twist_samples_from_capture_csv(path: str | Path, source: str = "auto") -> list[TwistSample]:
    rows = list(csv.DictReader(Path(path).open(newline="", encoding="utf-8")))
    samples: list[TwistSample] = []
    for row in rows:
        t_s = _float(row.get("t_s"))
        linear_x, angular_z, resolved = _select_twist(row, source)
        samples.append(TwistSample(t_s=t_s, linear_x=linear_x, angular_z=angular_z, source=resolved))
    return samples


def write_path_csv(path: str | Path, points: Iterable[SimPoint]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["t_s", "x_m", "y_m", "yaw_rad", "yaw_deg", "linear_x", "angular_z", "source"],
        )
        writer.writeheader()
        for point in points:
            writer.writerow(
                {
                    "t_s": f"{point.t_s:.6f}",
                    "x_m": f"{point.x_m:.6f}",
                    "y_m": f"{point.y_m:.6f}",
                    "yaw_rad": f"{point.yaw_rad:.6f}",
                    "yaw_deg": f"{math.degrees(point.yaw_rad):.3f}",
                    "linear_x": f"{point.linear_x:.6f}",
                    "angular_z": f"{point.angular_z:.6f}",
                    "source": point.source,
                }
            )
    return output


def write_summary_json(path: str | Path, summary: dict[str, object]) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return output


def write_path_svg(path: str | Path, points: Sequence[SimPoint], width: int = 720, height: int = 520) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not points:
        output.write_text("", encoding="utf-8")
        return output

    pad = 40
    xs = [point.x_m for point in points]
    ys = [point.y_m for point in points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    span_x = max(max_x - min_x, 0.1)
    span_y = max(max_y - min_y, 0.1)
    scale = min((width - 2 * pad) / span_x, (height - 2 * pad) / span_y)

    def project(point: SimPoint) -> tuple[float, float]:
        px = pad + (point.x_m - min_x) * scale
        py = height - pad - (point.y_m - min_y) * scale
        return px, py

    polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y in (project(point) for point in points))
    start_x, start_y = project(points[0])
    end_x, end_y = project(points[-1])
    final = points[-1]
    arrow_x = end_x + 22.0 * math.cos(final.yaw_rad)
    arrow_y = end_y - 22.0 * math.sin(final.yaw_rad)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <rect width="100%" height="100%" fill="#f8fafc"/>
  <line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" stroke="#94a3b8" stroke-width="1"/>
  <line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height - pad}" stroke="#94a3b8" stroke-width="1"/>
  <polyline points="{polyline}" fill="none" stroke="#0f766e" stroke-width="4" stroke-linejoin="round" stroke-linecap="round"/>
  <circle cx="{start_x:.2f}" cy="{start_y:.2f}" r="6" fill="#2563eb"/>
  <circle cx="{end_x:.2f}" cy="{end_y:.2f}" r="7" fill="#dc2626"/>
  <line x1="{end_x:.2f}" y1="{end_y:.2f}" x2="{arrow_x:.2f}" y2="{arrow_y:.2f}" stroke="#dc2626" stroke-width="3" stroke-linecap="round"/>
  <text x="{pad}" y="24" font-family="Arial, sans-serif" font-size="14" fill="#334155">UGV 2D simulated path</text>
  <text x="{pad}" y="{height - 12}" font-family="Arial, sans-serif" font-size="12" fill="#64748b">blue=start, red=end</text>
</svg>
"""
    output.write_text(svg, encoding="utf-8")
    return output


def write_map_html(path: str | Path, points: Sequence[SimPoint], summary: dict[str, object] | None = None) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "points": points_to_dicts(points),
        "summary": summary or {},
    }
    data_json = json.dumps(payload, ensure_ascii=False)
    html = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>UGV 2D Trajectory Map</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #172033;
      --muted: #647084;
      --grid: #d7dde6;
      --axis: #8c98aa;
      --path: #067a6f;
      --path-hot: #c2410c;
      --start: #1d4ed8;
      --end: #be123c;
      --robot: #111827;
      --control: #e9edf3;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ height: 100%; margin: 0; }}
    body {{
      font-family: Arial, Helvetica, sans-serif;
      background: var(--bg);
      color: var(--ink);
      overflow: hidden;
    }}
    .app {{
      height: 100%;
      display: grid;
      grid-template-rows: 48px 1fr 52px;
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 16px;
      border-bottom: 1px solid #dde3eb;
      background: var(--panel);
    }}
    h1 {{
      margin: 0;
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .metrics {{
      display: flex;
      gap: 18px;
      align-items: center;
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }}
    .metric strong {{
      color: var(--ink);
      font-weight: 700;
      margin-left: 5px;
    }}
    main {{
      position: relative;
      min-height: 0;
    }}
    canvas {{
      width: 100%;
      height: 100%;
      display: block;
      background: #fbfcfe;
    }}
    .legend {{
      position: absolute;
      right: 14px;
      top: 14px;
      display: flex;
      gap: 12px;
      align-items: center;
      padding: 8px 10px;
      background: rgba(255, 255, 255, 0.92);
      border: 1px solid #dce3ec;
      border-radius: 6px;
      color: var(--muted);
      font-size: 12px;
    }}
    .dot {{
      width: 10px;
      height: 10px;
      border-radius: 50%;
      display: inline-block;
      margin-right: 5px;
      vertical-align: -1px;
    }}
    .start {{ background: var(--start); }}
    .end {{ background: var(--end); }}
    .path {{ background: var(--path); }}
    footer {{
      display: grid;
      grid-template-columns: auto 1fr auto;
      gap: 12px;
      align-items: center;
      padding: 8px 14px;
      border-top: 1px solid #dde3eb;
      background: var(--panel);
    }}
    button {{
      height: 34px;
      min-width: 62px;
      border: 1px solid #cbd5e1;
      background: var(--control);
      color: var(--ink);
      font: inherit;
      font-size: 13px;
      border-radius: 6px;
      cursor: pointer;
    }}
    button:hover {{ background: #dfe6ef; }}
    input[type="range"] {{
      width: 100%;
      accent-color: var(--path);
    }}
    .time {{
      min-width: 150px;
      color: var(--muted);
      text-align: right;
      font-variant-numeric: tabular-nums;
      font-size: 13px;
    }}
    @media (max-width: 720px) {{
      header {{ align-items: flex-start; padding: 7px 10px; height: auto; }}
      .app {{ grid-template-rows: auto 1fr 50px; }}
      .metrics {{ gap: 9px; flex-wrap: wrap; font-size: 12px; justify-content: flex-end; }}
      h1 {{ font-size: 14px; }}
      .legend {{ left: 10px; right: auto; top: 10px; }}
      footer {{ grid-template-columns: auto 1fr; }}
      .time {{ display: none; }}
    }}
  </style>
</head>
<body>
  <div class="app">
    <header>
      <h1>UGV 2D Trajectory Map</h1>
      <div class="metrics">
        <span class="metric">distance<strong id="distance">0.000 m</strong></span>
        <span class="metric">x<strong id="posX">0.000 m</strong></span>
        <span class="metric">y<strong id="posY">0.000 m</strong></span>
        <span class="metric">yaw<strong id="yaw">0.0 deg</strong></span>
      </div>
    </header>
    <main>
      <canvas id="map"></canvas>
      <div class="legend">
        <span><i class="dot start"></i>start</span>
        <span><i class="dot path"></i>path</span>
        <span><i class="dot end"></i>end</span>
      </div>
    </main>
    <footer>
      <button id="play" title="Play or pause trajectory playback">Play</button>
      <input id="slider" type="range" min="0" max="0" value="0" step="1" title="Trajectory time index">
      <div class="time" id="time">0.00 s / 0.00 s</div>
    </footer>
  </div>
  <script id="trajectory-data" type="application/json">{data_json}</script>
  <script>
    const payload = JSON.parse(document.getElementById("trajectory-data").textContent);
    const points = payload.points || [];
    const canvas = document.getElementById("map");
    const ctx = canvas.getContext("2d");
    const slider = document.getElementById("slider");
    const play = document.getElementById("play");
    const distanceEl = document.getElementById("distance");
    const posXEl = document.getElementById("posX");
    const posYEl = document.getElementById("posY");
    const yawEl = document.getElementById("yaw");
    const timeEl = document.getElementById("time");
    let index = 0;
    let playing = false;
    let timer = null;
    slider.max = Math.max(points.length - 1, 0);

    function resize() {{
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * ratio));
      canvas.height = Math.max(1, Math.floor(rect.height * ratio));
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      draw();
    }}

    function bounds() {{
      if (!points.length) return {{ minX: -1, maxX: 1, minY: -1, maxY: 1 }};
      const xs = points.map(p => p.x_m);
      const ys = points.map(p => p.y_m);
      let minX = Math.min(...xs), maxX = Math.max(...xs);
      let minY = Math.min(...ys), maxY = Math.max(...ys);
      const span = Math.max(maxX - minX, maxY - minY, 0.5);
      const cx = (minX + maxX) / 2;
      const cy = (minY + maxY) / 2;
      const pad = span * 0.18 + 0.15;
      return {{ minX: cx - span / 2 - pad, maxX: cx + span / 2 + pad, minY: cy - span / 2 - pad, maxY: cy + span / 2 + pad }};
    }}

    function projector() {{
      const b = bounds();
      const rect = canvas.getBoundingClientRect();
      const pad = 42;
      const scale = Math.min((rect.width - pad * 2) / (b.maxX - b.minX), (rect.height - pad * 2) / (b.maxY - b.minY));
      return p => {{
        return {{
          x: pad + (p.x_m - b.minX) * scale,
          y: rect.height - pad - (p.y_m - b.minY) * scale,
          scale
        }};
      }};
    }}

    function drawGrid(project) {{
      const rect = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, rect.width, rect.height);
      ctx.fillStyle = "#fbfcfe";
      ctx.fillRect(0, 0, rect.width, rect.height);
      const b = bounds();
      const step = chooseStep(Math.max(b.maxX - b.minX, b.maxY - b.minY) / 8);
      ctx.lineWidth = 1;
      ctx.strokeStyle = "#d7dde6";
      ctx.fillStyle = "#647084";
      ctx.font = "12px Arial";
      for (let x = Math.ceil(b.minX / step) * step; x <= b.maxX; x += step) {{
        const a = project({{ x_m: x, y_m: b.minY }});
        ctx.beginPath();
        ctx.moveTo(a.x, 36);
        ctx.lineTo(a.x, rect.height - 36);
        ctx.stroke();
        ctx.fillText(x.toFixed(1), a.x + 3, rect.height - 18);
      }}
      for (let y = Math.ceil(b.minY / step) * step; y <= b.maxY; y += step) {{
        const a = project({{ x_m: b.minX, y_m: y }});
        ctx.beginPath();
        ctx.moveTo(36, a.y);
        ctx.lineTo(rect.width - 36, a.y);
        ctx.stroke();
        ctx.fillText(y.toFixed(1), 8, a.y - 4);
      }}
      ctx.strokeStyle = "#8c98aa";
      const ox = project({{ x_m: 0, y_m: b.minY }}).x;
      const oy = project({{ x_m: b.minX, y_m: 0 }}).y;
      ctx.beginPath();
      ctx.moveTo(ox, 36);
      ctx.lineTo(ox, rect.height - 36);
      ctx.moveTo(36, oy);
      ctx.lineTo(rect.width - 36, oy);
      ctx.stroke();
    }}

    function chooseStep(raw) {{
      const pow = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 0.001))));
      const norm = raw / pow;
      if (norm < 1.5) return pow;
      if (norm < 3.5) return 2 * pow;
      if (norm < 7.5) return 5 * pow;
      return 10 * pow;
    }}

    function drawPath(project) {{
      if (points.length < 2) return;
      ctx.lineWidth = 4;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.strokeStyle = "#067a6f";
      ctx.beginPath();
      points.slice(0, index + 1).forEach((p, i) => {{
        const q = project(p);
        if (i === 0) ctx.moveTo(q.x, q.y);
        else ctx.lineTo(q.x, q.y);
      }});
      ctx.stroke();

      ctx.lineWidth = 2;
      ctx.strokeStyle = "rgba(100, 112, 132, 0.45)";
      ctx.beginPath();
      points.forEach((p, i) => {{
        const q = project(p);
        if (i === 0) ctx.moveTo(q.x, q.y);
        else ctx.lineTo(q.x, q.y);
      }});
      ctx.stroke();
    }}

    function drawRobot(project) {{
      if (!points.length) return;
      const p = points[index];
      const q = project(p);
      const size = 15;
      ctx.save();
      ctx.translate(q.x, q.y);
      ctx.rotate(-p.yaw_rad);
      ctx.fillStyle = "#111827";
      ctx.beginPath();
      ctx.moveTo(size, 0);
      ctx.lineTo(-size * 0.65, -size * 0.55);
      ctx.lineTo(-size * 0.65, size * 0.55);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }}

    function drawMarkers(project) {{
      if (!points.length) return;
      const start = project(points[0]);
      const end = project(points[points.length - 1]);
      ctx.fillStyle = "#1d4ed8";
      ctx.beginPath();
      ctx.arc(start.x, start.y, 6, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#be123c";
      ctx.beginPath();
      ctx.arc(end.x, end.y, 7, 0, Math.PI * 2);
      ctx.fill();
    }}

    function draw() {{
      const project = projector();
      drawGrid(project);
      drawPath(project);
      drawMarkers(project);
      drawRobot(project);
      updateMetrics();
    }}

    function updateMetrics() {{
      const p = points[index] || {{ t_s: 0, x_m: 0, y_m: 0, yaw_rad: 0 }};
      const summary = payload.summary || {{}};
      distanceEl.textContent = Number(summary.path_distance_m || 0).toFixed(3) + " m";
      posXEl.textContent = Number(p.x_m || 0).toFixed(3) + " m";
      posYEl.textContent = Number(p.y_m || 0).toFixed(3) + " m";
      yawEl.textContent = (Number(p.yaw_rad || 0) * 180 / Math.PI).toFixed(1) + " deg";
      const last = points[points.length - 1] || {{ t_s: 0 }};
      timeEl.textContent = Number(p.t_s || 0).toFixed(2) + " s / " + Number(last.t_s || 0).toFixed(2) + " s";
      slider.value = index;
    }}

    function tick() {{
      if (!playing) return;
      index += 1;
      if (index >= points.length) {{
        index = points.length - 1;
        playing = false;
        play.textContent = "Play";
        clearInterval(timer);
      }}
      draw();
    }}

    play.addEventListener("click", () => {{
      if (!points.length) return;
      playing = !playing;
      play.textContent = playing ? "Pause" : "Play";
      if (playing) {{
        if (index >= points.length - 1) index = 0;
        clearInterval(timer);
        timer = setInterval(tick, 45);
      }} else {{
        clearInterval(timer);
      }}
      draw();
    }});

    slider.addEventListener("input", () => {{
      index = Number(slider.value);
      playing = false;
      play.textContent = "Play";
      clearInterval(timer);
      draw();
    }});

    window.addEventListener("resize", resize);
    resize();
  </script>
</body>
</html>
"""
    output.write_text(html, encoding="utf-8")
    return output


def write_live_state_json(
    path: str | Path,
    points: Sequence[SimPoint],
    summary: dict[str, object],
    metadata: dict[str, object] | None = None,
    complete: bool = False,
    max_points: int = 700,
    compact: bool = True,
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    latest = points[-1] if points else None
    payload = {
        "complete": complete,
        "sequence": len(points),
        "point": asdict(latest) if latest else None,
        "summary": summary,
        "metadata": metadata or {},
    }
    if not compact:
        payload["points"] = points_to_dicts(_sample_points_for_payload(points, max_points))
    temp_output = output.with_name(output.name + ".tmp")
    temp_output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temp_output.replace(output)
    return output


def _sample_points_for_payload(points: Sequence[SimPoint], max_points: int) -> list[SimPoint]:
    if max_points <= 0 or len(points) <= max_points:
        return list(points)
    step = max(1, math.ceil(len(points) / max_points))
    sampled = list(points[::step])
    if sampled[-1] is not points[-1]:
        sampled.append(points[-1])
    return sampled


def write_live_map_html(path: str | Path, refresh_ms: int = 300) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    html = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Live UGV 2D Map</title>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ height: 100%; margin: 0; }}
    body {{ font-family: Arial, Helvetica, sans-serif; background: #f6f7f9; color: #172033; overflow: hidden; }}
    .app {{ height: 100%; display: grid; grid-template-rows: 48px 1fr 42px; }}
    header, footer {{ background: #fff; border-color: #dde3eb; display: flex; align-items: center; padding: 0 14px; }}
    header {{ border-bottom: 1px solid #dde3eb; justify-content: space-between; }}
    footer {{ border-top: 1px solid #dde3eb; color: #647084; font-size: 13px; gap: 14px; }}
    h1 {{ margin: 0; font-size: 15px; }}
    .metrics {{ display: flex; gap: 16px; color: #647084; font-size: 13px; }}
    .metrics strong {{ color: #172033; margin-left: 5px; }}
    main {{ position: relative; min-height: 0; }}
    canvas {{ width: 100%; height: 100%; display: block; background: #fbfcfe; }}
    .badge {{ position: absolute; right: 12px; top: 12px; background: rgba(255,255,255,.94); border: 1px solid #dce3ec; border-radius: 6px; padding: 8px 10px; color: #647084; font-size: 12px; }}
    .ok {{ color: #047857; font-weight: 700; }}
    .done {{ color: #be123c; font-weight: 700; }}
  </style>
</head>
<body>
  <div class="app">
    <header>
      <h1>Live UGV 2D Map</h1>
      <div class="metrics">
        <span>x<strong id="x">0.000 m</strong></span>
        <span>y<strong id="y">0.000 m</strong></span>
        <span>yaw<strong id="yaw">0.0 deg</strong></span>
        <span>distance<strong id="dist">0.000 m</strong></span>
      </div>
    </header>
    <main>
      <canvas id="map"></canvas>
      <div class="badge">status <span id="status" class="ok">live</span></div>
    </main>
    <footer>
      <span id="time">0.00 s</span>
      <span id="samples">0 samples</span>
      <span>blue=start, red=current/end</span>
    </footer>
  </div>
  <script>
    const refreshMs = {refresh_ms};
    const canvas = document.getElementById("map");
    const ctx = canvas.getContext("2d");
    const xEl = document.getElementById("x");
    const yEl = document.getElementById("y");
    const yawEl = document.getElementById("yaw");
    const distEl = document.getElementById("dist");
    const timeEl = document.getElementById("time");
    const samplesEl = document.getElementById("samples");
    const statusEl = document.getElementById("status");
    let payload = {{ points: [], summary: {{}}, complete: false }};
    let localPoints = [];
    let lastSequence = 0;
    let lastUpdateAt = performance.now();
    let viewport = null;
    let connectionStatus = "waiting";
    const predictionEnabled = false;

    function resize() {{
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * ratio));
      canvas.height = Math.max(1, Math.floor(rect.height * ratio));
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      viewport = null;
      draw();
    }}

    async function refresh() {{
      try {{
        const res = await fetch("live_state.json?ts=" + Date.now(), {{ cache: "no-store" }});
        if (res.ok) {{
          const next = await res.json();
          payload = next;
          ingestPayload(next);
          connectionStatus = next.complete ? "saved" : "live";
          lastUpdateAt = performance.now();
          draw();
        }} else {{
          connectionStatus = "http " + res.status;
        }}
      }} catch (error) {{
        connectionStatus = localPoints.length ? "offline" : "waiting";
      }}
    }}

    function ingestPayload(next) {{
      if (Array.isArray(next.points) && next.points.length) {{
        localPoints = next.points.slice();
        lastSequence = Number(next.sequence || localPoints.length);
        return;
      }}
      if (!next.point) return;
      const sequence = Number(next.sequence || 0);
      const point = next.point;
      if (!localPoints.length) {{
        localPoints.push(point);
        lastSequence = sequence;
        return;
      }}
      if (sequence > lastSequence) {{
        localPoints.push(point);
        lastSequence = sequence;
      }} else if (sequence === lastSequence) {{
        localPoints[localPoints.length - 1] = point;
      }}
    }}

    function displayPoints() {{
      const points = localPoints;
      if (!predictionEnabled) return points;
      if (!points.length || payload.complete) return points;
      const latest = points[points.length - 1];
      const v = Number(latest.linear_x || 0);
      const w = Number(latest.angular_z || 0);
      if (Math.abs(v) < 1e-6 && Math.abs(w) < 1e-6) return points;
      const dt = Math.min((performance.now() - lastUpdateAt) / 1000, Math.max(0.15, refreshMs / 1000 * 1.5));
      const yaw = Number(latest.yaw_rad || 0);
      const yawMid = yaw + 0.5 * w * dt;
      const predicted = {{
        ...latest,
        t_s: Number(latest.t_s || 0) + dt,
        x_m: Number(latest.x_m || 0) + v * Math.cos(yawMid) * dt,
        y_m: Number(latest.y_m || 0) + v * Math.sin(yawMid) * dt,
        yaw_rad: normalizeAngle(yaw + w * dt),
      }};
      return points.concat([predicted]);
    }}

    function normalizeAngle(angle) {{
      return Math.atan2(Math.sin(angle), Math.cos(angle));
    }}

    function bounds(points, rect) {{
      const usableW = Math.max(rect.width - 84, 1);
      const usableH = Math.max(rect.height - 84, 1);
      const viewAspect = usableW / usableH;
      if (!viewport) {{
        const origin = points[0] || {{ x_m: 0, y_m: 0 }};
        const initialSpanY = 4.0;
        viewport = {{
          centerX: Number(origin.x_m || 0),
          centerY: Number(origin.y_m || 0),
          spanX: initialSpanY * viewAspect,
          spanY: initialSpanY,
          aspect: viewAspect,
        }};
      }}
      if (Math.abs(viewport.aspect - viewAspect) > 0.02) {{
        viewport.spanX = viewport.spanY * viewAspect;
        viewport.aspect = viewAspect;
      }}
      let spanX = viewport.spanX;
      let spanY = viewport.spanY;
      const marginM = 0.45;
      points.forEach(p => {{
        const dx = Math.abs(Number(p.x_m || 0) - viewport.centerX) + marginM;
        const dy = Math.abs(Number(p.y_m || 0) - viewport.centerY) + marginM;
        spanX = Math.max(spanX, dx * 2);
        spanY = Math.max(spanY, dy * 2);
      }});
      if (spanX / spanY < viewAspect) {{
        spanX = spanY * viewAspect;
      }} else {{
        spanY = spanX / viewAspect;
      }}
      if (spanX > viewport.spanX * 1.03 || spanY > viewport.spanY * 1.03) {{
        viewport.spanX = spanX;
        viewport.spanY = spanY;
      }}
      return {{
        minX: viewport.centerX - viewport.spanX / 2,
        maxX: viewport.centerX + viewport.spanX / 2,
        minY: viewport.centerY - viewport.spanY / 2,
        maxY: viewport.centerY + viewport.spanY / 2,
      }};
    }}

    function draw() {{
      const points = displayPoints();
      const rect = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, rect.width, rect.height);
      ctx.fillStyle = "#fbfcfe";
      ctx.fillRect(0, 0, rect.width, rect.height);
      const b = bounds(localPoints.length ? localPoints : points, rect);
      const pad = 42;
      const scale = Math.min((rect.width - 2 * pad) / (b.maxX - b.minX), (rect.height - 2 * pad) / (b.maxY - b.minY));
      const project = p => ({{ x: pad + (p.x_m - b.minX) * scale, y: rect.height - pad - (p.y_m - b.minY) * scale }});
      drawGrid(rect, b, project);
      if (points.length) {{
        ctx.lineWidth = 4;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.strokeStyle = "#067a6f";
        ctx.beginPath();
        points.forEach((p, i) => {{
          const q = project(p);
          if (i === 0) ctx.moveTo(q.x, q.y);
          else ctx.lineTo(q.x, q.y);
        }});
        ctx.stroke();
        const start = project(points[0]);
        const current = project(points[points.length - 1]);
        ctx.fillStyle = "#1d4ed8";
        ctx.beginPath();
        ctx.arc(start.x, start.y, 6, 0, Math.PI * 2);
        ctx.fill();
        drawRobot(current, points[points.length - 1].yaw_rad || 0);
      }}
      updateMetrics(points);
    }}

    function drawGrid(rect, b, project) {{
      const step = chooseStep(Math.max(b.maxX - b.minX, b.maxY - b.minY) / 8);
      ctx.strokeStyle = "#d7dde6";
      ctx.lineWidth = 1;
      for (let gx = Math.ceil(b.minX / step) * step; gx <= b.maxX; gx += step) {{
        const p = project({{ x_m: gx, y_m: b.minY }});
        ctx.beginPath(); ctx.moveTo(p.x, 28); ctx.lineTo(p.x, rect.height - 28); ctx.stroke();
      }}
      for (let gy = Math.ceil(b.minY / step) * step; gy <= b.maxY; gy += step) {{
        const p = project({{ x_m: b.minX, y_m: gy }});
        ctx.beginPath(); ctx.moveTo(28, p.y); ctx.lineTo(rect.width - 28, p.y); ctx.stroke();
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

    function updateMetrics(points) {{
      const p = points[points.length - 1] || {{ t_s: 0, x_m: 0, y_m: 0, yaw_rad: 0 }};
      const summary = payload.summary || {{}};
      xEl.textContent = Number(p.x_m || 0).toFixed(3) + " m";
      yEl.textContent = Number(p.y_m || 0).toFixed(3) + " m";
      yawEl.textContent = (Number(p.yaw_rad || 0) * 180 / Math.PI).toFixed(1) + " deg";
      distEl.textContent = Number(summary.path_distance_m || 0).toFixed(3) + " m";
      timeEl.textContent = Number(p.t_s || 0).toFixed(2) + " s";
      samplesEl.textContent = (Number(payload.sequence || points.length)) + " samples";
      statusEl.textContent = connectionStatus;
      statusEl.className = connectionStatus === "live" ? "ok" : "done";
    }}

    window.addEventListener("resize", resize);
    resize();
    refresh();
    setInterval(refresh, refreshMs);
    requestAnimationFrame(function animate() {{
      draw();
      requestAnimationFrame(animate);
    }});
  </script>
</body>
</html>
"""
    output.write_text(html, encoding="utf-8")
    return output


def points_to_dicts(points: Iterable[SimPoint]) -> list[dict[str, object]]:
    return [asdict(point) for point in points]


def _select_twist(row: dict[str, str], source: str) -> tuple[float, float, str]:
    candidates = {
        "cmd_out": ("cmd_out_linear_x", "cmd_out_angular_z"),
        "cmd": ("cmd_linear_x", "cmd_angular_z"),
        "odom_twist": ("odom_linear_x", "odom_angular_z"),
    }
    if source != "auto":
        linear_key, angular_key = candidates[source]
        return _float(row.get(linear_key)), _float(row.get(angular_key)), source
    for resolved, (linear_key, angular_key) in candidates.items():
        linear_x = _float(row.get(linear_key))
        angular_z = _float(row.get(angular_key))
        if abs(linear_x) > 1e-9 or abs(angular_z) > 1e-9:
            return linear_x, angular_z, resolved
    return 0.0, 0.0, "auto_zero"


def _float(value: str | None) -> float:
    if value in {None, ""}:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0

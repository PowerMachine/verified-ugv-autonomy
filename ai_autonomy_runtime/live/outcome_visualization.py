from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any


def build_outcome_timeline(states: list[dict[str, Any]], max_samples: int = 1200) -> list[dict[str, Any]]:
    sampled = _sample_states(states, max_samples)
    first_wall_time = _first_wall_time(sampled)
    timeline: list[dict[str, Any]] = []
    for state in sampled:
        wall_time = _float_or_none(state.get("wall_time"))
        cmd_in = state.get("cmd_in") if isinstance(state.get("cmd_in"), dict) else {}
        cmd_out = state.get("cmd_out") if isinstance(state.get("cmd_out"), dict) else {}
        feedback = state.get("feedback") if isinstance(state.get("feedback"), dict) else {}
        status = state.get("status") if isinstance(state.get("status"), dict) else {}
        timeline.append(
            {
                "sample_idx": _int_or_none(state.get("sample_idx")),
                "t_s": 0.0 if wall_time is None or first_wall_time is None else max(0.0, wall_time - first_wall_time),
                "cmd_in_linear_x": _float(cmd_in.get("linear_x")),
                "cmd_in_angular_z": _float(cmd_in.get("angular_z")),
                "cmd_out_linear_x": _float(cmd_out.get("linear_x")),
                "cmd_out_angular_z": _float(cmd_out.get("angular_z")),
                "odom_available": bool(status.get("odom_available")),
                "feedback_available": isinstance(state.get("feedback"), dict),
                "left_velocity": _float_or_none(feedback.get("left_velocity")),
                "right_velocity": _float_or_none(feedback.get("right_velocity")),
            }
        )
    return timeline


def write_outcome_html(
    path: str | Path,
    *,
    review_payload: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_outcome_html(review_payload=review_payload, timeline=timeline), encoding="utf-8")
    return output


def render_outcome_html(*, review_payload: dict[str, Any], timeline: list[dict[str, Any]]) -> str:
    status = str(review_payload.get("status", "unknown"))
    command_id = str(review_payload.get("command_id") or "unknown")
    expected = review_payload.get("expected") if isinstance(review_payload.get("expected"), dict) else {}
    observed = review_payload.get("observed") if isinstance(review_payload.get("observed"), dict) else {}
    cmd_in = observed.get("cmd_in") if isinstance(observed.get("cmd_in"), dict) else {}
    cmd_out = observed.get("cmd_out") if isinstance(observed.get("cmd_out"), dict) else {}
    payload_json = _json_for_script({"review": review_payload, "timeline": timeline})
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>UGV Outcome Review</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Arial, Helvetica, sans-serif;
      color: #182033;
      background: #f5f7fa;
    }}
    header {{
      padding: 20px 24px 16px;
      background: #ffffff;
      border-bottom: 1px solid #dce3ec;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 22px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    .subtle {{ color: #667085; font-size: 13px; overflow-wrap: anywhere; }}
    .status {{
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 700;
      margin-left: 8px;
      vertical-align: 2px;
    }}
    .success {{ background: #e7f5ef; color: #047857; }}
    .partial {{ background: #fff3d9; color: #9a5a00; }}
    .anomaly, .exception_required {{ background: #feeceb; color: #b42318; }}
    main {{ padding: 18px 24px 28px; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(5, minmax(150px, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }}
    .metric {{
      background: #ffffff;
      border: 1px solid #dce3ec;
      border-radius: 6px;
      padding: 10px 12px;
      min-height: 74px;
    }}
    .metric dt {{ color: #667085; font-size: 12px; margin-bottom: 8px; }}
    .metric dd {{ margin: 0; font-size: 20px; font-weight: 700; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }}
    .chart-wrap {{
      background: #ffffff;
      border: 1px solid #dce3ec;
      border-radius: 6px;
      padding: 12px;
    }}
    canvas {{
      display: block;
      width: 100%;
      height: 360px;
      background: #fbfcfe;
      border: 1px solid #edf1f6;
      border-radius: 4px;
    }}
    .legend {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      color: #667085;
      font-size: 12px;
      margin-top: 10px;
    }}
    .swatch {{ display: inline-block; width: 18px; height: 3px; margin-right: 6px; vertical-align: 3px; }}
    .in {{ background: #1d4ed8; }}
    .out {{ background: #067a6f; }}
    .expected {{ background: #9a5a00; }}
    .checks {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
      margin-top: 16px;
    }}
    .check {{
      background: #ffffff;
      border: 1px solid #dce3ec;
      border-radius: 6px;
      padding: 9px 10px;
      font-size: 13px;
    }}
    .check strong {{ display: block; margin-bottom: 4px; }}
    .pass strong {{ color: #047857; }}
    .fail strong {{ color: #b42318; }}
    @media (max-width: 900px) {{
      main, header {{ padding-left: 14px; padding-right: 14px; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .checks {{ grid-template-columns: 1fr; }}
      canvas {{ height: 300px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>UGV Outcome Review <span class="status {html.escape(status)}">{html.escape(status)}</span></h1>
    <div class="subtle">command_id={html.escape(command_id)}</div>
  </header>
  <main>
    <dl class="metrics">
      <div class="metric"><dt>Exception</dt><dd>{str(bool(review_payload.get("exception_required"))).lower()}</dd></div>
      <div class="metric"><dt>Samples</dt><dd>{int(observed.get("sample_count") or 0)}</dd></div>
      <div class="metric"><dt>Expected w</dt><dd>{_fmt(expected.get("angular_z"))}</dd></div>
      <div class="metric"><dt>cmd_in nonzero</dt><dd>{int(cmd_in.get("nonzero_samples") or 0)}</dd></div>
      <div class="metric"><dt>cmd_out nonzero</dt><dd>{int(cmd_out.get("nonzero_samples") or 0)}</dd></div>
    </dl>
    <section class="chart-wrap">
      <canvas id="timeline"></canvas>
      <div class="legend">
        <span><i class="swatch in"></i>cmd_in angular.z</span>
        <span><i class="swatch out"></i>cmd_out angular.z</span>
        <span><i class="swatch expected"></i>expected angular.z</span>
      </div>
    </section>
    <section id="checks" class="checks"></section>
  </main>
  <script id="payload" type="application/json">{payload_json}</script>
  <script>
    const payload = JSON.parse(document.getElementById("payload").textContent);
    const review = payload.review;
    const timeline = payload.timeline || [];
    const canvas = document.getElementById("timeline");
    const ctx = canvas.getContext("2d");

    function resize() {{
      const rect = canvas.getBoundingClientRect();
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * ratio));
      canvas.height = Math.max(1, Math.floor(rect.height * ratio));
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      draw();
    }}

    function draw() {{
      const rect = canvas.getBoundingClientRect();
      ctx.clearRect(0, 0, rect.width, rect.height);
      ctx.fillStyle = "#fbfcfe";
      ctx.fillRect(0, 0, rect.width, rect.height);
      const pad = {{ left: 52, right: 20, top: 24, bottom: 40 }};
      const w = Math.max(1, rect.width - pad.left - pad.right);
      const h = Math.max(1, rect.height - pad.top - pad.bottom);
      const expected = Number((review.expected || {{}}).angular_z || 0);
      const maxT = Math.max(1, ...timeline.map(p => Number(p.t_s || 0)));
      const maxY = Math.max(0.05, Math.abs(expected), ...timeline.flatMap(p => [Math.abs(Number(p.cmd_in_angular_z || 0)), Math.abs(Number(p.cmd_out_angular_z || 0))])) * 1.25;
      const project = (t, y) => ({{
        x: pad.left + Number(t || 0) / maxT * w,
        y: pad.top + (maxY - Number(y || 0)) / (maxY * 2) * h,
      }});
      grid(pad, w, h, maxT, maxY);
      line(timeline, "cmd_in_angular_z", "#1d4ed8", project);
      line(timeline, "cmd_out_angular_z", "#067a6f", project);
      expectedLine(expected, "#9a5a00", project, maxT);
      zeroLine(project, maxT);
      markers(timeline, "cmd_in_angular_z", "#1d4ed8", project);
      markers(timeline, "cmd_out_angular_z", "#067a6f", project);
    }}

    function grid(pad, w, h, maxT, maxY) {{
      ctx.strokeStyle = "#d7dde6";
      ctx.lineWidth = 1;
      ctx.fillStyle = "#667085";
      ctx.font = "12px Arial";
      for (let i = 0; i <= 4; i++) {{
        const y = pad.top + (h * i / 4);
        ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left + w, y); ctx.stroke();
        const value = maxY - (maxY * 2 * i / 4);
        ctx.fillText(value.toFixed(3), 8, y + 4);
      }}
      for (let i = 0; i <= 5; i++) {{
        const x = pad.left + (w * i / 5);
        ctx.beginPath(); ctx.moveTo(x, pad.top); ctx.lineTo(x, pad.top + h); ctx.stroke();
        ctx.fillText((maxT * i / 5).toFixed(1) + "s", x - 10, pad.top + h + 24);
      }}
    }}

    function line(points, key, color, project) {{
      if (!points.length) return;
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.beginPath();
      points.forEach((p, i) => {{
        const q = project(p.t_s, p[key]);
        if (i === 0) ctx.moveTo(q.x, q.y);
        else ctx.lineTo(q.x, q.y);
      }});
      ctx.stroke();
    }}

    function expectedLine(value, color, project, maxT) {{
      const a = project(0, value);
      const b = project(maxT, value);
      ctx.save();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.setLineDash([7, 5]);
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
      ctx.restore();
    }}

    function zeroLine(project, maxT) {{
      const a = project(0, 0);
      const b = project(maxT, 0);
      ctx.strokeStyle = "#98a2b3";
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
    }}

    function markers(points, key, color, project) {{
      ctx.fillStyle = color;
      points.forEach(p => {{
        const value = Number(p[key] || 0);
        if (Math.abs(value) <= 0.000001) return;
        const q = project(p.t_s, value);
        ctx.beginPath();
        ctx.arc(q.x, q.y, 5, 0, Math.PI * 2);
        ctx.fill();
      }});
    }}

    function checks() {{
      const root = document.getElementById("checks");
      root.innerHTML = "";
      (review.checks || []).forEach(item => {{
        const div = document.createElement("div");
        div.className = "check " + (item.passed ? "pass" : "fail");
        const strong = document.createElement("strong");
        strong.textContent = (item.passed ? "PASS " : "FAIL ") + item.check;
        const detail = document.createElement("div");
        detail.className = "subtle";
        detail.textContent = item.detail || "";
        div.appendChild(strong);
        div.appendChild(detail);
        root.appendChild(div);
      }});
    }}

    window.addEventListener("resize", resize);
    checks();
    resize();
  </script>
</body>
</html>
"""


def _sample_states(states: list[dict[str, Any]], max_samples: int) -> list[dict[str, Any]]:
    if max_samples <= 0 or len(states) <= max_samples:
        return list(states)
    step = max(1, math.ceil(len(states) / max_samples))
    sampled = list(states[::step])
    if sampled[-1] is not states[-1]:
        sampled.append(states[-1])
    return sampled


def _first_wall_time(states: list[dict[str, Any]]) -> float | None:
    for state in states:
        value = _float_or_none(state.get("wall_time"))
        if value is not None:
            return value
    return None


def _json_for_script(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def _fmt(value: Any) -> str:
    parsed = _float_or_none(value)
    return "-" if parsed is None else f"{parsed:.3f}"


def _float(value: Any) -> float:
    parsed = _float_or_none(value)
    return 0.0 if parsed is None else parsed


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

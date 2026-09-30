from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ai_autonomy_runtime.adapters.jackal.video_scenario_supervisor import run_video_scenario_supervisor


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a dry-run supervisor pass from a video-derived UGV scenario fixture."
    )
    parser.add_argument("--scenario-file", required=True, help="JSON scenario/perception fixture.")
    parser.add_argument("--output", default=None)
    parser.add_argument("--confidence-threshold", type=float, default=0.6)
    parser.add_argument("--human-approved", action="store_true")
    args = parser.parse_args()

    output_dir = Path(args.output or Path("local_outputs") / "video_scenario_supervisor" / _timestamp())
    scenario = _read_json(Path(args.scenario_file))
    summary = run_video_scenario_supervisor(
        scenario,
        output_dir=output_dir,
        confidence_threshold=args.confidence_threshold,
        human_approved=args.human_approved,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["accepted"]:
        raise SystemExit(2)


def _read_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise SystemExit("--scenario-file must contain a JSON object")
    return loaded


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    main()

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ai_autonomy_runtime.core.audit_logger import _to_jsonable
from ai_autonomy_runtime.core.config import load_yaml
from ai_autonomy_runtime.schemas.safety_envelope import SafetyEnvelope


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_default_safety() -> SafetyEnvelope:
    return SafetyEnvelope.from_config(load_yaml(PROJECT_ROOT / "configs" / "safety.yaml"))


def write_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        output.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_json(payload: Any) -> None:
    print(json.dumps(_to_jsonable(payload), ensure_ascii=False, indent=2))

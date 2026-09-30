from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml


ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def load_yaml(path: str | Path, expand_env: bool = True) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    if expand_env:
        text = ENV_PATTERN.sub(lambda match: os.environ.get(match.group(1), ""), text)
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in YAML file: {path}")
    return data

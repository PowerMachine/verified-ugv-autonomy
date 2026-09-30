from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RollbackPoint:
    name: str
    payload: dict[str, Any] = field(default_factory=dict)


class RollbackManager:
    def __init__(self) -> None:
        self._points: list[RollbackPoint] = []

    def register(self, name: str, payload: dict[str, Any] | None = None) -> RollbackPoint:
        point = RollbackPoint(name=name, payload=payload or {})
        self._points.append(point)
        return point

    def latest(self) -> RollbackPoint | None:
        return self._points[-1] if self._points else None

    def rollback(self) -> RollbackPoint | None:
        if not self._points:
            return None
        return self._points.pop()

    @property
    def available(self) -> bool:
        return bool(self._points)

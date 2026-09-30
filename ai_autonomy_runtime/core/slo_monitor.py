from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class SLOStatus:
    name: str
    budget_ms: float
    elapsed_ms: float
    passed: bool

    @property
    def margin_ms(self) -> float:
        return self.budget_ms - self.elapsed_ms


class SLOMonitor:
    def __init__(self, default_budget_ms: float = 500.0) -> None:
        self.default_budget_ms = float(default_budget_ms)
        self.statuses: list[SLOStatus] = []

    def check(self, name: str, elapsed_ms: float, budget_ms: float | None = None) -> SLOStatus:
        budget = self.default_budget_ms if budget_ms is None else float(budget_ms)
        status = SLOStatus(name=name, budget_ms=budget, elapsed_ms=float(elapsed_ms), passed=elapsed_ms <= budget)
        self.statuses.append(status)
        return status

    @contextmanager
    def measure(self, name: str, budget_ms: float | None = None) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            self.check(name=name, elapsed_ms=elapsed_ms, budget_ms=budget_ms)

    def latest(self, name: str | None = None) -> SLOStatus | None:
        for status in reversed(self.statuses):
            if name is None or status.name == name:
                return status
        return None

from __future__ import annotations

from collections.abc import Iterable

from ai_autonomy_runtime.core.event_bus import EventBus
from ai_autonomy_runtime.schemas.runtime_event import RuntimeEvent


class ReplayRunner:
    def __init__(self, event_bus: EventBus | None = None) -> None:
        self.event_bus = event_bus or EventBus()

    def replay(self, events: Iterable[RuntimeEvent]) -> int:
        count = 0
        for event in events:
            self.event_bus.publish(event)
            count += 1
        return count

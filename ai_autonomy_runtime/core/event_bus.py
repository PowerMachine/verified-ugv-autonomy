from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable

from ai_autonomy_runtime.schemas.runtime_event import RuntimeEvent


EventHandler = Callable[[RuntimeEvent], None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)
        self._history: list[RuntimeEvent] = []

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._subscribers[event_type].append(handler)

    def publish(self, event: RuntimeEvent) -> None:
        self._history.append(event)
        for handler in self._subscribers.get(str(event.event_type), []):
            handler(event)
        for handler in self._subscribers.get("*", []):
            handler(event)

    @property
    def history(self) -> list[RuntimeEvent]:
        return list(self._history)

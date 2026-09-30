from __future__ import annotations

from ai_autonomy_runtime.schemas.runtime_event import RuntimeEvent, RuntimeEventType


class SensorEventAdapter:
    def from_sensor_payload(self, source: str, payload: dict[str, object]) -> RuntimeEvent:
        event_type = RuntimeEventType.SENSOR_UPDATE
        if payload.get("path_blocked"):
            event_type = RuntimeEventType.PATH_BLOCKED
        elif payload.get("localization_uncertain"):
            event_type = RuntimeEventType.LOCALIZATION_UNCERTAIN
        return RuntimeEvent(event_type=event_type, source=source, payload=payload, requires_model_call=False)

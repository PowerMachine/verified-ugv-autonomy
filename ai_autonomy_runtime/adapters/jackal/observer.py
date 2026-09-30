from __future__ import annotations

from ai_autonomy_runtime.adapters.ros_common.topic_discovery import discover_ros_environment
from ai_autonomy_runtime.schemas.runtime_event import RuntimeEvent, RuntimeEventType


class JackalObserver:
    def observe_once(self) -> RuntimeEvent:
        discovery = discover_ros_environment()
        return RuntimeEvent(
            event_type=RuntimeEventType.SENSOR_UPDATE,
            source="jackal_observer",
            payload={"ros_discovery": discovery, "mode": "read_only"},
            requires_model_call=False,
        )

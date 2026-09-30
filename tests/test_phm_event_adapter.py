from __future__ import annotations

from ai_autonomy_runtime.adapters.phm.phm_event_adapter import PHMEventAdapter, PHMTriggerPolicy


def test_phm_adapter_emits_event_for_large_anomaly() -> None:
    adapter = PHMEventAdapter(policy=PHMTriggerPolicy(th_low=0.5, th_high=0.7, onset_k=2))
    adapter.fit_normal(
        ("ugv", "jackal_01"),
        [
            {"motor_temp": 20.0, "vibration": 0.1},
            {"motor_temp": 21.0, "vibration": 0.2},
            {"motor_temp": 19.0, "vibration": 0.1},
        ],
    )
    event = adapter.observe("ugv", "jackal_01", {"motor_temp": 80.0, "vibration": 10.0})
    assert event is not None
    assert event.payload["anomaly_score"] >= 0.7
    assert event.requires_model_call is True

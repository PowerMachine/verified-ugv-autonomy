from __future__ import annotations

from ai_autonomy_runtime.live.ugv_live_state import parse_telemetry_line


def test_parser_ignores_non_prefixed_lines() -> None:
    parsed = parse_telemetry_line("[INFO] ROS log line")
    assert parsed.kind == "ignored"


def test_parser_accepts_state_lines() -> None:
    parsed = parse_telemetry_line('UGV_STATE_JSON {"schema_version":"ugv_state.v1","sample_idx":1}')
    assert parsed.kind == "state"
    assert parsed.payload is not None
    assert parsed.payload["sample_idx"] == 1


def test_parser_accepts_event_lines() -> None:
    parsed = parse_telemetry_line('UGV_EVENT_JSON {"event_type":"topic_missing","topic":"/feedback"}')
    assert parsed.kind == "event"
    assert parsed.payload is not None
    assert parsed.payload["topic"] == "/feedback"


def test_parser_rejects_malformed_json_without_crashing() -> None:
    parsed = parse_telemetry_line("UGV_STATE_JSON {bad")
    assert parsed.kind == "malformed"
    assert parsed.error

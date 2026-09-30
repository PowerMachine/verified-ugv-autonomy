from __future__ import annotations

from pathlib import Path

from ai_autonomy_runtime.cli.run_mock_mission import run_mock_mission


def test_mock_mission_generates_audit_summary(tmp_path: Path) -> None:
    summary = run_mock_mission("simple_inspection", "full_governed", tmp_path)
    assert summary["verification_passed"] is True
    assert summary["promotion_decision"].decision == "limited_promote"
    run_dir = Path(str(summary["run_dir"]))
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "summary.json").exists()

from __future__ import annotations

import argparse

from ai_autonomy_runtime.adapters.jackal.safe_command_wrapper import SafeCommandWrapper
from ai_autonomy_runtime.cli.common import load_default_safety, print_json
from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate, ActionType
from ai_autonomy_runtime.schemas.common import RiskLevel


def main() -> None:
    parser = argparse.ArgumentParser(description="Run deterministic safety checks on a sample candidate.")
    parser.add_argument("--physical", action="store_true")
    args = parser.parse_args()
    candidate = ActionCandidate(
        action_type=ActionType.VELOCITY_CANDIDATE if args.physical else ActionType.REPORT_ONLY,
        parameters={"linear_x": 1.0, "angular_z": 1.0, "sequence_id": 1},
        ttl_ms=500,
        expected_duration_ms=100,
        risk_level=RiskLevel.MEDIUM if args.physical else RiskLevel.LOW,
        requires_physical_execution=args.physical,
        source_model="mock_model",
    )
    result = SafeCommandWrapper().evaluate(candidate, load_default_safety(), require_physical_gate=True)
    print_json({"candidate": candidate, "safety_result": result})


if __name__ == "__main__":
    main()

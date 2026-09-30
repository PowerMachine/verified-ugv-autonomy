from __future__ import annotations

import argparse
from pathlib import Path

from ai_autonomy_runtime.agent.artifact_generator import ArtifactGenerator
from ai_autonomy_runtime.agent.planner_agent import PlannerAgent
from ai_autonomy_runtime.cli.common import load_default_safety, print_json
from ai_autonomy_runtime.core.audit_logger import AuditLogger, create_run_dir
from ai_autonomy_runtime.core.autonomy_manager import AutonomyManager
from ai_autonomy_runtime.sandbox.dryrun_executor import DryRunExecutor
from ai_autonomy_runtime.schemas.runtime_event import RuntimeEvent, RuntimeEventType
from ai_autonomy_runtime.verifier.composite_verifier import CompositeVerifier


SCENARIO_GOALS = {
    "simple_inspection": "inspect the area and generate a read-only safety report",
    "stop_request": "stop and report current safety state",
}


def run_mock_mission(scenario: str, policy: str, output: str | Path) -> dict[str, object]:
    run_dir = create_run_dir(output)
    logger = AuditLogger(run_dir)
    envelope = load_default_safety()
    goal = SCENARIO_GOALS.get(scenario, scenario)

    event = RuntimeEvent(
        event_type=RuntimeEventType.USER_GOAL,
        source="cli.run_mock_mission",
        payload={"scenario": scenario, "goal": goal, "policy": policy},
        slo_budget_ms=500,
        requires_model_call=False,
    )
    logger.log_event(event)

    candidate = PlannerAgent().plan(goal)
    artifact = ArtifactGenerator().from_action_candidate(candidate)
    verification = CompositeVerifier().verify_action_artifact(candidate, artifact, envelope)
    dryrun = DryRunExecutor().execute(candidate, envelope)

    manager = AutonomyManager(logger)
    decision = manager.promote(
        artifact=artifact,
        verification_results=verification.results,
        slo_passed="slo" not in verification.failed_checks,
        operator_armed=envelope.operator_armed,
        safety_passed=dryrun.success,
        evidence_score=float(artifact.metadata.get("evidence_score", 1.0)),
        model_confidence=1.0,
    )
    logger.log_safety_check(dryrun)
    summary = {
        "run_dir": str(run_dir),
        "scenario": scenario,
        "candidate": candidate,
        "dryrun": dryrun,
        "verification_passed": verification.passed,
        "failed_checks": verification.failed_checks,
        "promotion_decision": decision,
        "physical_execution": False,
    }
    logger.write_summary(summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a governed mock mission without robot motion.")
    parser.add_argument("--scenario", default="simple_inspection")
    parser.add_argument("--policy", default="full_governed")
    parser.add_argument("--output", default="runs/mock_simple")
    args = parser.parse_args()
    print_json(run_mock_mission(args.scenario, args.policy, args.output))


if __name__ == "__main__":
    main()

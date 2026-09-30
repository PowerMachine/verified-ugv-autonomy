from __future__ import annotations

from ai_autonomy_runtime.sandbox.dryrun_executor import DryRunExecutor, DryRunResult
from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate
from ai_autonomy_runtime.schemas.safety_envelope import SafetyEnvelope


class JackalDryRunAdapter:
    def __init__(self) -> None:
        self.executor = DryRunExecutor()

    def run(self, candidate: ActionCandidate, envelope: SafetyEnvelope) -> DryRunResult:
        return self.executor.execute(candidate, envelope)

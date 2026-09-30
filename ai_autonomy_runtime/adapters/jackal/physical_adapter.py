from __future__ import annotations

from ai_autonomy_runtime.adapters.jackal.safe_command_wrapper import SafeCommandWrapper, SafetyWrapperResult
from ai_autonomy_runtime.schemas.action_candidate import ActionCandidate
from ai_autonomy_runtime.schemas.safety_envelope import SafetyEnvelope


class JackalPhysicalAdapter:
    def __init__(self) -> None:
        self.wrapper = SafeCommandWrapper()

    def execute(self, candidate: ActionCandidate, envelope: SafetyEnvelope) -> SafetyWrapperResult:
        result = self.wrapper.evaluate(candidate, envelope, require_physical_gate=True)
        if not result.accepted:
            return result
        return SafetyWrapperResult(
            accepted=False,
            reason="physical execution adapter intentionally disabled in initial milestone",
            checks={**result.checks, "initial_milestone_physical_block": False},
            clamped_command=result.clamped_command,
            metadata=result.metadata,
        )

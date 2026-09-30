from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VLMResponse:
    answer: str
    confidence: float
    latency_ms: float


class StubVLMClient:
    def answer(self, question: str, image_ref: str | None = None) -> VLMResponse:
        return VLMResponse(
            answer=f"Mock VLM cannot inspect {image_ref or 'no image'}; question was: {question}",
            confidence=0.0,
            latency_ms=0.0,
        )

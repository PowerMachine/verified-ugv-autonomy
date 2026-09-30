from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMResponse:
    text: str
    backend_name: str
    model: str
    latency_ms: float
    prompt_tokens: int | None = None
    output_tokens: int | None = None


class LLMClient(Protocol):
    backend_name: str
    model: str

    def generate(self, prompt: str, max_tokens: int = 256, temperature: float = 0.0) -> LLMResponse:
        ...

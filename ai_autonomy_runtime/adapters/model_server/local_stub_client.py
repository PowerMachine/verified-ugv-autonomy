from __future__ import annotations

import json
import time

from ai_autonomy_runtime.adapters.model_server.llm_client import LLMResponse


class LocalStubLLMClient:
    backend_name = "mock_model"
    model = "deterministic_stub"

    def generate(self, prompt: str, max_tokens: int = 256, temperature: float = 0.0) -> LLMResponse:
        start = time.perf_counter()
        payload = {
            "action_type": "report_only",
            "parameters": {"report": "Mock model suggests read-only inspection and no physical motion.", "prompt_hash": hash(prompt) % 100000},
            "ttl_ms": 1000,
            "expected_duration_ms": 100,
            "risk_level": "low",
            "requires_physical_execution": False,
            "source_model": self.model,
        }
        text = json.dumps(payload, ensure_ascii=False)
        return LLMResponse(
            text=text,
            backend_name=self.backend_name,
            model=self.model,
            latency_ms=(time.perf_counter() - start) * 1000.0,
            prompt_tokens=len(prompt.split()),
            output_tokens=len(text.split()),
        )

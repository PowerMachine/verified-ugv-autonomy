from __future__ import annotations

from ai_autonomy_runtime.adapters.model_server.local_stub_client import LocalStubLLMClient


def run_model_latency_benchmark(models: list[str], prompt: str = "Generate a safe report-only candidate.") -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for model in models:
        client = LocalStubLLMClient()
        client.backend_name = "mock_model" if model == "mock" else f"simulated_{model}"
        client.model = model
        response = client.generate(prompt=prompt, max_tokens=128, temperature=0.0)
        rows.append(
            {
                "model": model,
                "backend": response.backend_name,
                "latency_ms": response.latency_ms,
                "prompt_tokens": response.prompt_tokens,
                "output_tokens": response.output_tokens,
                "success": True,
            }
        )
    return rows

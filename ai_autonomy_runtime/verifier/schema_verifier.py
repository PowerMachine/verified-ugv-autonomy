from __future__ import annotations

import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from ai_autonomy_runtime.schemas.verification_result import VerificationResult

ModelT = TypeVar("ModelT", bound=BaseModel)


class SchemaVerifier:
    name = "schema"

    def verify(self, payload: Any, schema_model: type[ModelT] | None = None) -> VerificationResult:
        start = time.perf_counter()
        try:
            if schema_model is not None and not isinstance(payload, schema_model):
                schema_model.model_validate(payload)
            elif not isinstance(payload, BaseModel):
                raise TypeError("payload is not a pydantic model")
            return VerificationResult(
                checker_name=self.name,
                passed=True,
                reason="schema_valid",
                latency_ms=(time.perf_counter() - start) * 1000.0,
            )
        except (ValidationError, TypeError, ValueError) as exc:
            return VerificationResult(
                checker_name=self.name,
                passed=False,
                reason=f"schema_invalid: {exc}",
                latency_ms=(time.perf_counter() - start) * 1000.0,
            )

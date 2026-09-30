from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

from ai_autonomy_runtime.schemas.common import Severity
from ai_autonomy_runtime.schemas.runtime_event import RuntimeEvent, RuntimeEventType


MachineKey = tuple[str, str]


@dataclass(frozen=True)
class GaussianModel:
    mean: np.ndarray
    inv_cov: np.ndarray
    q_low: float
    q_high: float


class GaussianMahalanobisTrigger:
    """Generic PHM event trigger adapted from the CBM+ Mahalanobis trigger."""

    def __init__(self, eps_cov: float = 1e-6, q_low: float = 0.50, q_high: float = 0.99) -> None:
        self.eps_cov = float(eps_cov)
        self.q_low = float(q_low)
        self.q_high = float(q_high)
        self.models: dict[MachineKey, GaussianModel] = {}

    def fit(self, normal_features_by_machine: dict[MachineKey, np.ndarray]) -> None:
        self.models = {}
        for machine_key, matrix in normal_features_by_machine.items():
            if matrix.ndim != 2 or matrix.shape[0] < 2:
                continue
            mean = matrix.mean(axis=0)
            cov = np.cov(matrix, rowvar=False)
            if cov.ndim == 0:
                cov = np.eye(matrix.shape[1], dtype=np.float64)
            cov = cov + np.eye(cov.shape[0], dtype=np.float64) * self.eps_cov
            inv_cov = np.linalg.pinv(cov)
            distances = np.array([_mahalanobis(row, mean, inv_cov) for row in matrix], dtype=np.float64)
            self.models[machine_key] = GaussianModel(
                mean=mean.astype(np.float64),
                inv_cov=inv_cov.astype(np.float64),
                q_low=float(np.quantile(distances, self.q_low)),
                q_high=float(np.quantile(distances, self.q_high)),
            )

    def score(self, features: np.ndarray, machine_key: MachineKey | None) -> float:
        if machine_key is None or machine_key not in self.models:
            return 0.5
        model = self.models[machine_key]
        distance = _mahalanobis(features.astype(np.float64), model.mean, model.inv_cov)
        denominator = model.q_high - model.q_low
        if denominator <= 1e-12:
            return float(np.clip(distance / (model.q_high + 1e-9), 0.0, 1.0))
        return float(np.clip((distance - model.q_low) / denominator, 0.0, 1.0))


@dataclass
class PHMTriggerPolicy:
    th_low: float = 0.6
    th_high: float = 0.8
    onset_k: int = 3
    slo_budget_ms: int = 500


class PHMEventAdapter:
    def __init__(self, trigger: GaussianMahalanobisTrigger | None = None, policy: PHMTriggerPolicy | None = None) -> None:
        self.trigger = trigger or GaussianMahalanobisTrigger()
        self.policy = policy or PHMTriggerPolicy()
        self._history: dict[MachineKey, list[float]] = {}

    def fit_normal(self, machine_key: MachineKey, normal_metric_rows: Iterable[dict[str, float]]) -> None:
        rows = [self._vectorize(row) for row in normal_metric_rows]
        if rows:
            self.trigger.fit({machine_key: np.vstack(rows)})

    def observe(self, machine_type: str, machine_id: str, metrics: dict[str, float]) -> RuntimeEvent | None:
        machine_key = (machine_type, machine_id)
        vector = self._vectorize(metrics)
        anomaly_score = self.trigger.score(vector, machine_key)
        history = self._history.setdefault(machine_key, [])
        history.append(anomaly_score)
        if len(history) > self.policy.onset_k:
            del history[:-self.policy.onset_k]
        onset = len(history) >= self.policy.onset_k and all(score >= self.policy.th_low for score in history)
        high = anomaly_score >= self.policy.th_high
        if not onset and not high:
            return None
        return RuntimeEvent(
            event_type=RuntimeEventType.SENSOR_UPDATE,
            source="phm_event_adapter",
            payload={
                "machine_type": machine_type,
                "machine_id": machine_id,
                "metrics": metrics,
                "anomaly_score": anomaly_score,
                "trigger_level": "high" if high else "onset",
            },
            severity=Severity.WARNING if high else Severity.INFO,
            slo_budget_ms=self.policy.slo_budget_ms,
            requires_model_call=high,
        )

    def _vectorize(self, metrics: dict[str, float]) -> np.ndarray:
        values = [float(metrics[key]) for key in sorted(metrics)]
        if not values:
            values = [0.0]
        return np.array(values, dtype=np.float64)


def _mahalanobis(row: np.ndarray, mean: np.ndarray, inv_cov: np.ndarray) -> float:
    delta = (row - mean).reshape(-1, 1)
    return float(np.sqrt(np.maximum(delta.T @ inv_cov @ delta, 0.0)).item())

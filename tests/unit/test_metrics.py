"""Tests for evaluation metrics."""

from __future__ import annotations

from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Inline functions under test
# ---------------------------------------------------------------------------
def compute_crps(posterior_samples: np.ndarray, actuals: np.ndarray) -> float:
    n_samples = posterior_samples.shape[0]
    abs_diff = np.mean(np.abs(posterior_samples - actuals[None, :]), axis=0)
    spread = 0.0
    for i in range(n_samples):
        for j in range(i + 1, n_samples):
            spread += np.mean(np.abs(posterior_samples[i] - posterior_samples[j]))
    spread = spread / (n_samples * (n_samples - 1) / 2) if n_samples > 1 else 0.0
    return float(np.mean(abs_diff) - 0.5 * spread)


def compute_wape(predicted: np.ndarray, actuals: np.ndarray) -> float:
    denom = np.sum(np.abs(actuals))
    if denom == 0:
        return float("nan")
    return float(np.sum(np.abs(actuals - predicted)) / denom)


def compute_rmsle(predicted: np.ndarray, actuals: np.ndarray) -> float:
    mask = actuals > 0
    if not np.any(mask):
        return float("nan")
    log_pred = np.log1p(np.clip(predicted[mask], 0, None))
    log_act = np.log1p(actuals[mask])
    return float(np.sqrt(np.mean((log_pred - log_act) ** 2)))


def compute_bias(predicted: np.ndarray, actuals: np.ndarray) -> float:
    denom = np.sum(actuals)
    if denom == 0:
        return float("nan")
    return float(np.sum(predicted - actuals) / denom)


def compute_interval_coverage(lower: np.ndarray, upper: np.ndarray, actuals: np.ndarray, nominal: float = 0.94) -> float:
    covered = (actuals >= lower) & (actuals <= upper)
    return float(np.mean(covered))


def check_elasticity_sign(posterior_samples: np.ndarray) -> dict[str, float]:
    if posterior_samples.ndim == 1:
        posterior_samples = posterior_samples[:, None]
    prob_neg = float(np.mean(posterior_samples < 0))
    return {"prob_negative": prob_neg, "passes": float(prob_neg >= 0.95)}


def check_elasticity_magnitude(posterior_samples: np.ndarray, bounds: tuple[float, float] | None = None) -> dict[str, Any]:
    if bounds is None:
        bounds = (-2.5, -0.2)
    mean = float(np.mean(posterior_samples))
    in_band = bounds[0] <= mean <= bounds[1]
    return {"mean": mean, "bounds": bounds, "in_band": in_band}


def run_placebo_test(model_fn, data: np.ndarray, fake_date_idx: int) -> dict[str, Any]:
    result = model_fn(data, fake_date_idx)
    passes = result["lower"] <= 0.0 <= result["upper"]
    return {"placebo_mean": result["mean"], "ci": (result["lower"], result["upper"]), "passes": passes}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_compute_wape():
    predicted = np.array([10.0, 20.0, 30.0])
    actuals = np.array([12.0, 18.0, 33.0])
    wape = compute_wape(predicted, actuals)
    expected = (2 + 2 + 3) / (12 + 18 + 33)
    assert abs(wape - expected) < 1e-6


def test_compute_rmsle():
    predicted = np.array([10.0, 20.0, 0.0])
    actuals = np.array([12.0, 18.0, 0.0])
    rmsle = compute_rmsle(predicted, actuals)
    log_p = np.log1p(np.array([10.0, 20.0]))
    log_a = np.log1p(np.array([12.0, 18.0]))
    expected = np.sqrt(np.mean((log_p - log_a) ** 2))
    assert abs(rmsle - expected) < 1e-6


def test_compute_bias():
    predicted = np.array([11.0, 21.0, 31.0])
    actuals = np.array([10.0, 20.0, 30.0])
    bias = compute_bias(predicted, actuals)
    assert abs(bias - 0.05) < 1e-6


def test_compute_interval_coverage():
    lower = np.array([8.0, 17.0, 28.0])
    upper = np.array([12.0, 22.0, 32.0])
    actuals = np.array([10.0, 25.0, 30.0])
    cov = compute_interval_coverage(lower, upper, actuals)
    assert abs(cov - 2.0 / 3.0) < 1e-6


def test_check_elasticity_sign():
    samples = np.array([-1.0, -0.5, -2.0, -1.5, -0.8] * 20)
    result = check_elasticity_sign(samples)
    assert result["prob_negative"] == 1.0
    assert result["passes"] == 1.0

    samples_mixed = np.array([-1.0, 0.5, -0.3, 0.2])
    result2 = check_elasticity_sign(samples_mixed)
    assert result2["prob_negative"] == 0.5
    assert result2["passes"] == 0.0


def test_check_elasticity_magnitude():
    samples = np.random.normal(-1.0, 0.1, size=1000)
    result = check_elasticity_magnitude(samples, bounds=(-2.5, -0.2))
    assert result["in_band"] is True
    assert abs(result["mean"] - (-1.0)) < 0.1

    samples_hi = np.random.normal(0.5, 0.1, size=1000)
    result2 = check_elasticity_magnitude(samples_hi, bounds=(-2.5, -0.2))
    assert result2["in_band"] is False


def test_compute_crps():
    actuals = np.array([1.0, 2.0, 3.0])
    samples = np.tile(actuals, (50, 1))
    crps = compute_crps(samples, actuals)
    assert abs(crps) < 1e-6


def test_run_placebo_test():
    def mock_model(data, date_idx):
        return {"mean": 0.01, "lower": -0.1, "upper": 0.12}

    result = run_placebo_test(mock_model, np.zeros(10), fake_date_idx=5)
    assert result["passes"] is True

    def mock_model_fail(data, date_idx):
        return {"mean": 0.5, "lower": 0.2, "upper": 0.8}

    result2 = run_placebo_test(mock_model_fail, np.zeros(10), fake_date_idx=5)
    assert result2["passes"] is False

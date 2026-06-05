"""Tests for evaluation metrics."""

import numpy as np


def test_compute_wape():
    from pricing.evaluation.metrics import compute_wape

    predicted = np.array([10.0, 20.0, 30.0])
    actuals = np.array([12.0, 18.0, 33.0])
    wape = compute_wape(predicted, actuals)
    expected = (2 + 2 + 3) / (12 + 18 + 33)
    assert abs(wape - expected) < 1e-6


def test_compute_rmsle():
    from pricing.evaluation.metrics import compute_rmsle

    predicted = np.array([10.0, 20.0, 0.0])
    actuals = np.array([12.0, 18.0, 0.0])
    rmsle = compute_rmsle(predicted, actuals)
    # Only uses indices where actuals > 0 (first two)
    log_p = np.log1p(np.array([10.0, 20.0]))
    log_a = np.log1p(np.array([12.0, 18.0]))
    expected = np.sqrt(np.mean((log_p - log_a) ** 2))
    assert abs(rmsle - expected) < 1e-6


def test_compute_bias():
    from pricing.evaluation.metrics import compute_bias

    predicted = np.array([11.0, 21.0, 31.0])
    actuals = np.array([10.0, 20.0, 30.0])
    bias = compute_bias(predicted, actuals)
    # (1+1+1) / (10+20+30) = 3/60 = 0.05
    assert abs(bias - 0.05) < 1e-6


def test_compute_interval_coverage():
    from pricing.evaluation.metrics import compute_interval_coverage

    lower = np.array([8.0, 17.0, 28.0])
    upper = np.array([12.0, 22.0, 32.0])
    actuals = np.array([10.0, 25.0, 30.0])
    cov = compute_interval_coverage(lower, upper, actuals)
    # 10 in [8,12] ✓, 25 in [17,22] ✗, 30 in [28,32] ✓ → 2/3
    assert abs(cov - 2.0 / 3.0) < 1e-6


def test_check_elasticity_sign():
    from pricing.evaluation.metrics import check_elasticity_sign

    # All negative → should pass
    samples = np.array([-1.0, -0.5, -2.0, -1.5, -0.8] * 20)
    result = check_elasticity_sign(samples)
    assert result["prob_negative"] == 1.0
    assert result["passes"] == 1.0

    # Mixed → should fail
    samples_mixed = np.array([-1.0, 0.5, -0.3, 0.2])
    result2 = check_elasticity_sign(samples_mixed)
    assert result2["prob_negative"] == 0.5
    assert result2["passes"] == 0.0


def test_check_elasticity_magnitude():
    from pricing.evaluation.metrics import check_elasticity_magnitude

    samples = np.random.normal(-1.0, 0.1, size=1000)
    result = check_elasticity_magnitude(samples, bounds=(-2.5, -0.2))
    assert result["in_band"] is True
    assert abs(result["mean"] - (-1.0)) < 0.1

    # Out of band
    samples_hi = np.random.normal(0.5, 0.1, size=1000)
    result2 = check_elasticity_magnitude(samples_hi, bounds=(-2.5, -0.2))
    assert result2["in_band"] is False


def test_compute_crps():
    from pricing.evaluation.metrics import compute_crps

    # Perfect prediction: all samples equal actuals → CRPS ≈ 0
    actuals = np.array([1.0, 2.0, 3.0])
    samples = np.tile(actuals, (50, 1))  # (50, 3)
    crps = compute_crps(samples, actuals)
    assert abs(crps) < 1e-6


def test_run_placebo_test():
    from pricing.evaluation.metrics import run_placebo_test

    def mock_model(data, date_idx):
        return {"mean": 0.01, "lower": -0.1, "upper": 0.12}

    result = run_placebo_test(mock_model, np.zeros(10), fake_date_idx=5)
    assert result["passes"] is True

    def mock_model_fail(data, date_idx):
        return {"mean": 0.5, "lower": 0.2, "upper": 0.8}

    result2 = run_placebo_test(mock_model_fail, np.zeros(10), fake_date_idx=5)
    assert result2["passes"] is False

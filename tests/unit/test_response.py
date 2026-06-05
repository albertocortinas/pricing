"""Smoke tests for the SCAN*PRO PyMC response model."""

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def synthetic_data():
    """Create a small synthetic dataset for model testing."""
    rng = np.random.default_rng(42)
    n = 50
    price_ratio = rng.uniform(0.8, 1.2, n)
    ln_price_ratio = np.log(price_ratio)
    price_increase_flag = (price_ratio > 1.0).astype(float)
    month = rng.integers(1, 13, n)

    # True DGP: ln(q) = 5 - 1.0*ln(p) + 0.3*ln(p)*I(p>1) + noise
    ln_volume = 5.0 - 1.0 * ln_price_ratio + 0.3 * ln_price_ratio * price_increase_flag + rng.normal(0, 0.2, n)

    return pd.DataFrame({
        "ln_volume": ln_volume,
        "ln_price_ratio": ln_price_ratio,
        "price_increase_flag": price_increase_flag,
        "month": month,
    })


def test_build_pymc_model(synthetic_data):
    """Verify model builds without error."""
    from pricing.models.response import build_pymc_model

    model = build_pymc_model(synthetic_data)
    assert model is not None
    # Check key variables exist
    var_names = [v.name for v in model.free_RVs]
    assert "beta_base" in var_names
    assert "beta_up" in var_names
    assert "alpha" in var_names


def test_fit_segment_smoke(synthetic_data):
    """Smoke test: model samples successfully on tiny data."""
    from pricing.models.response import fit_segment

    idata = fit_segment(
        synthetic_data,
        sample_kwargs={"draws": 50, "tune": 50, "chains": 1, "cores": 1},
    )
    assert "posterior" in idata.groups()
    assert "beta_base" in idata.posterior
    assert "beta_up" in idata.posterior

    # Check sign: beta_base should be negative (true value = -1.0)
    beta_mean = float(idata.posterior["beta_base"].mean())
    assert beta_mean < 0, f"Expected negative beta_base, got {beta_mean}"

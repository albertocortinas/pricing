"""Smoke tests for the SCAN*PRO PyMC response model."""

import numpy as np
import pandas as pd
import pymc as pm
import pytest


# ---------------------------------------------------------------------------
# Inline config
# ---------------------------------------------------------------------------
ELASTICITY_PRIOR_RANGE = (-2.5, -0.2)


# ---------------------------------------------------------------------------
# Inline functions under test
# ---------------------------------------------------------------------------
def build_pymc_model(df, condition_cols=None, hierarchy_cols=None):
    if condition_cols is None:
        condition_cols = []

    y = df["ln_volume"].values.astype(float)
    x_price = df["ln_price_ratio"].values.astype(float)
    x_up = (df["price_increase_flag"].values * x_price).astype(float)
    month_idx = df["month"].values.astype(int) - 1

    coords = {"obs": np.arange(len(y)), "month": np.arange(12)}

    with pm.Model(coords=coords) as model:
        alpha = pm.Normal("alpha", mu=0.0, sigma=5.0)  # noqa: F841

        prior_lo, prior_hi = ELASTICITY_PRIOR_RANGE
        prior_mu = (prior_lo + prior_hi) / 2.0
        beta_base = pm.Normal("beta_base", mu=prior_mu, sigma=0.5)
        beta_up = pm.HalfNormal("beta_up", sigma=0.3)

        sigma_month = pm.HalfNormal("sigma_month", sigma=0.3)
        gamma = pm.Normal("gamma", mu=0.0, sigma=sigma_month, dims="month")

        deltas = {}
        for col in condition_cols:
            deltas[col] = pm.Normal(f"delta_{col}", mu=0.0, sigma=1.0)

        sigma = pm.HalfNormal("sigma", sigma=1.0)

        mu = alpha + beta_base * x_price + beta_up * x_up + gamma[month_idx]
        for col in condition_cols:
            mu = mu + deltas[col] * df[col].values.astype(float)

        pm.Normal("y_obs", mu=mu, sigma=sigma, observed=y, dims="obs")
        pm.Deterministic("mu_pred", mu, dims="obs")

    return model


def fit_segment(df, condition_cols=None, sample_kwargs=None):
    if sample_kwargs is None:
        sample_kwargs = {}

    defaults = dict(
        draws=1000, tune=500, chains=2, cores=1,
        target_accept=0.9, return_inferencedata=True,
        idata_kwargs={"log_likelihood": True}, progressbar=False,
    )
    defaults.update(sample_kwargs)

    model = build_pymc_model(df, condition_cols=condition_cols)
    with model:
        idata = pm.sample(**defaults)
        pm.sample_posterior_predictive(idata, extend_inferencedata=True)
    return idata


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def synthetic_data():
    rng = np.random.default_rng(42)
    n = 50
    price_ratio = rng.uniform(0.8, 1.2, n)
    ln_price_ratio = np.log(price_ratio)
    price_increase_flag = (price_ratio > 1.0).astype(float)
    month = rng.integers(1, 13, n)

    ln_volume = 5.0 - 1.0 * ln_price_ratio + 0.3 * ln_price_ratio * price_increase_flag + rng.normal(0, 0.2, n)

    return pd.DataFrame({
        "ln_volume": ln_volume,
        "ln_price_ratio": ln_price_ratio,
        "price_increase_flag": price_increase_flag,
        "month": month,
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_build_pymc_model(synthetic_data):
    model = build_pymc_model(synthetic_data)
    assert model is not None
    var_names = [v.name for v in model.free_RVs]
    assert "beta_base" in var_names
    assert "beta_up" in var_names
    assert "alpha" in var_names


def test_fit_segment_smoke(synthetic_data):
    idata = fit_segment(
        synthetic_data,
        sample_kwargs={"draws": 50, "tune": 50, "chains": 1, "cores": 1},
    )
    assert "posterior" in idata.groups()
    assert "beta_base" in idata.posterior
    assert "beta_up" in idata.posterior

    beta_mean = float(idata.posterior["beta_base"].mean())
    assert beta_mean < 0, f"Expected negative beta_base, got {beta_mean}"

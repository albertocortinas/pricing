"""SCAN*PRO log-log response model with asymmetric elasticity and hierarchical Bayesian shrinkage.

The model is estimated per segment using PyMC, then distributed across Spark
via ``applyInPandas``.
"""

from __future__ import annotations

from typing import Any

import arviz as az
import numpy as np
import pandas as pd
import pymc as pm
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql.types import (
    DoubleType,
    StringType,
    StructField,
    StructType,
)

from pricing import config

# Schema for the posterior summary returned by the distributed fit
POSTERIOR_SCHEMA = StructType([
    StructField("segment_key", StringType()),
    StructField("parameter", StringType()),
    StructField("mean", DoubleType()),
    StructField("sd", DoubleType()),
    StructField("hdi_3", DoubleType()),
    StructField("hdi_97", DoubleType()),
    StructField("r_hat", DoubleType()),
    StructField("n_obs", DoubleType()),
])


# ---------------------------------------------------------------------------
# PyMC model builder
# ---------------------------------------------------------------------------

def build_pymc_model(
    df: pd.DataFrame,
    condition_cols: list[str] | None = None,
    hierarchy_cols: list[str] | None = None,
) -> pm.Model:
    """Build the SCAN*PRO PyMC model on a pandas DataFrame.

    Expected columns in *df*:
        ln_volume, ln_price_ratio, price_increase_flag, month,
        and any columns listed in *condition_cols*.

    Parameters
    ----------
    condition_cols : list[str]
        Binary/continuous condition indicators (promo flags, discount dummies).
    hierarchy_cols : list[str]
        Columns used to build hierarchical intercepts.  Currently unused in the
        within-segment model but reserved for future multi-level expansion.
    """
    if condition_cols is None:
        condition_cols = []

    y = df["ln_volume"].values.astype(float)
    x_price = df["ln_price_ratio"].values.astype(float)
    x_up = (df["price_increase_flag"].values * x_price).astype(float)
    month_idx = df["month"].values.astype(int) - 1  # 0-indexed

    coords = {"obs": np.arange(len(y)), "month": np.arange(12)}

    with pm.Model(coords=coords) as model:
        # --- Priors ---
        alpha = pm.Normal("alpha", mu=0.0, sigma=5.0)  # global intercept

        # Base price elasticity — prior centred on literature mean
        prior_lo, prior_hi = config.ELASTICITY_PRIOR_RANGE
        prior_mu = (prior_lo + prior_hi) / 2.0
        beta_base = pm.Normal("beta_base", mu=prior_mu, sigma=0.5)

        # Asymmetry: extra (positive) effect for price increases
        beta_up = pm.HalfNormal("beta_up", sigma=0.3)

        # Monthly seasonal effects (hierarchical)
        sigma_month = pm.HalfNormal("sigma_month", sigma=0.3)
        gamma = pm.Normal("gamma", mu=0.0, sigma=sigma_month, dims="month")

        # Condition semi-elasticities
        deltas = {}
        for col in condition_cols:
            deltas[col] = pm.Normal(f"delta_{col}", mu=0.0, sigma=1.0)

        # Noise
        sigma = pm.HalfNormal("sigma", sigma=1.0)

        # --- Deterministic mean ---
        mu = alpha + beta_base * x_price + beta_up * x_up + gamma[month_idx]
        for col in condition_cols:
            mu = mu + deltas[col] * df[col].values.astype(float)

        # --- Likelihood ---
        pm.Normal("y_obs", mu=mu, sigma=sigma, observed=y, dims="obs")

        # Posterior predictive
        pm.Deterministic("mu_pred", mu, dims="obs")

    return model


# ---------------------------------------------------------------------------
# Fitting helpers
# ---------------------------------------------------------------------------

def fit_segment(
    df: pd.DataFrame,
    condition_cols: list[str] | None = None,
    sample_kwargs: dict[str, Any] | None = None,
) -> az.InferenceData:
    """Build and sample the SCAN*PRO model for a single segment.

    Returns an ArviZ ``InferenceData`` with posterior, posterior_predictive,
    and log_likelihood groups.
    """
    if sample_kwargs is None:
        sample_kwargs = {}

    defaults = dict(
        draws=1000,
        tune=500,
        chains=2,
        cores=1,
        target_accept=0.9,
        return_inferencedata=True,
        idata_kwargs={"log_likelihood": True},
        progressbar=False,
    )
    defaults.update(sample_kwargs)

    model = build_pymc_model(df, condition_cols=condition_cols)
    with model:
        idata = pm.sample(**defaults)
        pm.sample_posterior_predictive(idata, extend_inferencedata=True)
    return idata


def _summarize_idata(idata: az.InferenceData, segment_key: str, n_obs: int) -> list[dict]:
    """Extract posterior summaries into flat rows."""
    summary = az.summary(idata, hdi_prob=0.94, var_names=["~mu_pred"])
    rows = []
    for param in summary.index:
        rows.append({
            "segment_key": segment_key,
            "parameter": str(param),
            "mean": float(summary.loc[param, "mean"]),
            "sd": float(summary.loc[param, "sd"]),
            "hdi_3": float(summary.loc[param, "hdi_3%"]),
            "hdi_97": float(summary.loc[param, "hdi_97%"]),
            "r_hat": float(summary.loc[param, "r_hat"]),
            "n_obs": float(n_obs),
        })
    return rows


# ---------------------------------------------------------------------------
# Distributed fitting via Spark applyInPandas
# ---------------------------------------------------------------------------

def fit_model_distributed(
    spark: SparkSession,
    features_df: DataFrame,
    group_cols: list[str],
    condition_cols: list[str] | None = None,
    sample_kwargs: dict[str, Any] | None = None,
) -> DataFrame:
    """Fit the model per segment using ``applyInPandas``.

    Parameters
    ----------
    features_df : DataFrame
        Must contain: ln_volume, ln_price_ratio, price_increase_flag, month,
        plus *group_cols* and *condition_cols*.
    group_cols : list[str]
        Columns to group by — each group is estimated independently.

    Returns a Spark DataFrame matching ``POSTERIOR_SCHEMA``.
    """
    _cond_cols = condition_cols or []
    _sample_kw = sample_kwargs or {}

    def _fit_udf(pdf: pd.DataFrame) -> pd.DataFrame:
        required = {"ln_volume", "ln_price_ratio", "price_increase_flag", "month"}
        if not required.issubset(pdf.columns) or len(pdf) < 10:
            return pd.DataFrame(columns=[f.name for f in POSTERIOR_SCHEMA.fields])

        seg_key = "|".join(str(pdf[c].iloc[0]) for c in group_cols)
        try:
            idata = fit_segment(pdf, condition_cols=_cond_cols, sample_kwargs=_sample_kw)
            rows = _summarize_idata(idata, seg_key, len(pdf))
        except Exception:
            return pd.DataFrame(columns=[f.name for f in POSTERIOR_SCHEMA.fields])
        return pd.DataFrame(rows)

    return features_df.groupBy(*group_cols).applyInPandas(_fit_udf, schema=POSTERIOR_SCHEMA)

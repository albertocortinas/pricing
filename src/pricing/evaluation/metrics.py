"""Three-layer evaluation metrics for the pricing response model.

Layer 1 — Fit quality
Layer 2 — Causal validity (gate)
Layer 3 — Decision value
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pyspark.sql.functions as F
from pyspark.sql import DataFrame


# =====================================================================
# Layer 1 — Fit
# =====================================================================

def compute_crps(posterior_samples: np.ndarray, actuals: np.ndarray) -> float:
    """Continuous Ranked Probability Score (lower is better).

    Parameters
    ----------
    posterior_samples : ndarray, shape (n_samples, n_obs)
    actuals : ndarray, shape (n_obs,)
    """
    n_samples = posterior_samples.shape[0]
    abs_diff = np.mean(np.abs(posterior_samples - actuals[None, :]), axis=0)
    # Pairwise spread term
    spread = 0.0
    for i in range(n_samples):
        for j in range(i + 1, n_samples):
            spread += np.mean(np.abs(posterior_samples[i] - posterior_samples[j]))
    spread = spread / (n_samples * (n_samples - 1) / 2) if n_samples > 1 else 0.0
    return float(np.mean(abs_diff) - 0.5 * spread)


def compute_wape(predicted: np.ndarray, actuals: np.ndarray) -> float:
    """Weighted Absolute Percentage Error = Σ|y-ŷ| / Σ|y|."""
    denom = np.sum(np.abs(actuals))
    if denom == 0:
        return float("nan")
    return float(np.sum(np.abs(actuals - predicted)) / denom)


def compute_rmsle(predicted: np.ndarray, actuals: np.ndarray) -> float:
    """Root Mean Squared Logarithmic Error (only where volume > 0)."""
    mask = actuals > 0
    if not np.any(mask):
        return float("nan")
    log_pred = np.log1p(np.clip(predicted[mask], 0, None))
    log_act = np.log1p(actuals[mask])
    return float(np.sqrt(np.mean((log_pred - log_act) ** 2)))


def compute_bias(predicted: np.ndarray, actuals: np.ndarray) -> float:
    """Aggregate bias = Σ(ŷ-y) / Σy."""
    denom = np.sum(actuals)
    if denom == 0:
        return float("nan")
    return float(np.sum(predicted - actuals) / denom)


def compute_interval_coverage(
    lower: np.ndarray,
    upper: np.ndarray,
    actuals: np.ndarray,
    nominal: float = 0.94,
) -> float:
    """Fraction of actuals falling within [lower, upper]."""
    covered = (actuals >= lower) & (actuals <= upper)
    return float(np.mean(covered))


# =====================================================================
# Layer 2 — Causal gate
# =====================================================================

def check_elasticity_sign(posterior_samples: np.ndarray) -> dict[str, float]:
    """Check P(β < 0) per column of posterior_samples.

    Parameters
    ----------
    posterior_samples : ndarray, shape (n_draws,) or (n_draws, n_segments)
        Posterior draws for the price elasticity parameter.

    Returns
    -------
    dict with ``prob_negative`` and ``passes`` (threshold 0.95).
    """
    if posterior_samples.ndim == 1:
        posterior_samples = posterior_samples[:, None]

    results: dict[str, float] = {}
    prob_neg = float(np.mean(posterior_samples < 0))
    results["prob_negative"] = prob_neg
    results["passes"] = float(prob_neg >= 0.95)
    return results


def check_elasticity_magnitude(
    posterior_samples: np.ndarray,
    bounds: tuple[float, float] | None = None,
) -> dict[str, Any]:
    """Check whether posterior mean falls within plausible band."""
    if bounds is None:
        from pricing.config import ELASTICITY_PRIOR_RANGE
        bounds = ELASTICITY_PRIOR_RANGE

    mean = float(np.mean(posterior_samples))
    in_band = bounds[0] <= mean <= bounds[1]
    return {"mean": mean, "bounds": bounds, "in_band": in_band}


def run_placebo_test(
    model_fn,
    data: np.ndarray,
    fake_date_idx: int,
) -> dict[str, Any]:
    """Estimate 'effect' at a false intervention date.

    The test passes if the resulting confidence interval includes zero,
    confirming no spurious effect.

    Parameters
    ----------
    model_fn : callable
        ``model_fn(data, date_idx) -> dict`` with keys ``mean``, ``lower``, ``upper``.
    data : ndarray
        Input data array.
    fake_date_idx : int
        Index of the placebo intervention point.
    """
    result = model_fn(data, fake_date_idx)
    passes = result["lower"] <= 0.0 <= result["upper"]
    return {"placebo_mean": result["mean"], "ci": (result["lower"], result["upper"]), "passes": passes}


# =====================================================================
# Layer 3 — Decision value
# =====================================================================

def compute_margin_uplift(
    current_policy: DataFrame,
    model_policy: DataFrame,
    response_surface: DataFrame,
) -> dict[str, float]:
    """Compute expected margin uplift of model policy vs. current.

    Both policy DataFrames should have columns: segment_key, price, expected_volume.
    """
    current = (
        current_policy
        .withColumn("margin_current", F.col("price") * F.col("expected_volume"))
        .agg(F.sum("margin_current").alias("total_current"))
        .collect()[0]["total_current"]
    )
    model = (
        model_policy
        .withColumn("margin_model", F.col("price") * F.col("expected_volume"))
        .agg(F.sum("margin_model").alias("total_model"))
        .collect()[0]["total_model"]
    )
    if current and current != 0:
        uplift_pct = (model - current) / abs(current) * 100
    else:
        uplift_pct = float("nan")

    return {
        "margin_current": float(current) if current else 0.0,
        "margin_model": float(model) if model else 0.0,
        "uplift_pct": float(uplift_pct),
    }


# =====================================================================
# Validation scheme
# =====================================================================

def temporal_split(
    df: DataFrame,
    date_col: str = "periodo",
    method: str = "rolling_origin",
    n_splits: int = 4,
) -> list[tuple[DataFrame, DataFrame]]:
    """Split a panel temporally for evaluation.

    Parameters
    ----------
    method : str
        ``"rolling_origin"`` — expanding train window, fixed-size test.
        ``"leave_one_quarter_out"`` — hold out one calendar quarter at a time.
    """
    dates = sorted(
        row[date_col] for row in df.select(date_col).distinct().collect()
    )

    splits: list[tuple[DataFrame, DataFrame]] = []

    if method == "rolling_origin":
        step = max(1, len(dates) // (n_splits + 1))
        for i in range(1, n_splits + 1):
            cutoff = dates[min(i * step, len(dates) - 1)]
            train = df.filter(F.col(date_col) < cutoff)
            test = df.filter(
                (F.col(date_col) >= cutoff)
                & (F.col(date_col) < dates[min(i * step + step, len(dates) - 1)])
            )
            if train.count() > 0 and test.count() > 0:
                splits.append((train, test))
    else:  # leave_one_quarter_out
        df_q = df.withColumn("_quarter", F.quarter(date_col))
        for q in range(1, 5):
            train = df_q.filter(F.col("_quarter") != q).drop("_quarter")
            test = df_q.filter(F.col("_quarter") == q).drop("_quarter")
            if train.count() > 0 and test.count() > 0:
                splits.append((train, test))

    return splits

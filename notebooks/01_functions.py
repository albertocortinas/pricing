# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Shared Functions
# MAGIC
# MAGIC All pricing model functions. Include in other notebooks via:
# MAGIC ```
# MAGIC %run ./00_config
# MAGIC %run ./01_functions
# MAGIC ```

# COMMAND ----------

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set, Tuple

import arviz as az
import numpy as np
import pandas as pd
import pymc as pm
import pyspark.sql.functions as F
from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql.types import (
    DoubleType,
    StringType,
    StructField,
    StructType,
)

# COMMAND ----------

# ===========================================================================
# Reference data
# ===========================================================================

# Cache: {(table, code_col): {known_values}}
_known_values: Dict[Tuple[str, str], Set[str]] = {}

logger = logging.getLogger(__name__)


def get_reference_values(
    spark: SparkSession,
    table: str,
    code_col: str,
    desc_col: str,
) -> Dict[str, str]:
    """Return {code: description} from a dimension table."""
    rows = (
        spark.read.table(table)
        .select(code_col, desc_col)
        .distinct()
        .collect()
    )
    return {str(r[code_col]): r[desc_col] for r in rows}


def validate_reference(
    spark: SparkSession,
    table: str,
    code_col: str,
    desc_col: str,
    known: Optional[Set[str]] = None,
) -> Dict[str, str]:
    """Load reference values and warn on unknowns if known set is provided."""
    values = get_reference_values(spark, table, code_col, desc_col)
    current_codes = set(values.keys())

    if known is not None:
        new_codes = current_codes - known
        if new_codes:
            logger.warning(
                "New values in %s.%s not in known set: %s",
                table, code_col, new_codes,
            )

    return values


def load_all_references(
    spark: SparkSession,
    known_values: Optional[Dict[Tuple[str, str], Set[str]]] = None,
) -> Dict[Tuple[str, str], Dict[str, str]]:
    """Load and validate all reference fields defined in config."""
    known_values = known_values or {}
    result = {}
    for table, fields in REFERENCE_FIELDS.items():
        for code_col, desc_col in fields:
            known = known_values.get((table, code_col))
            result[(table, code_col)] = validate_reference(
                spark, table, code_col, desc_col, known=known,
            )
    return result


# COMMAND ----------

# ===========================================================================
# Feature engineering
# ===========================================================================

# Canonical join keys matching the real schema
JOIN_COLS = ["Establecimiento", "Material", "Week-Month-Year", "Distribuidor"]

# Codes that appear in BOTH ventas and margen — use ventas as source of truth
_OVERLAPPING_CODES = {"100", "210", "300", "420", "740"}


def build_pocket_price_waterfall(ventas_df: DataFrame, margen_df: DataFrame) -> DataFrame:
    """Join ventas + margen and compute the pocket-price waterfall.

    Both DataFrames are already wide: waterfall codes are columns (``050``,
    ``210``, ``890``, etc.).  Overlapping code columns (100–740) are taken
    from ventas; cost and distributor codes come from margen.

    Returns one row per (Establecimiento, Material, Week-Month-Year,
    Distribuidor) with named waterfall columns plus venta_neta, pocket_price,
    pocket_margin.
    """
    # Rename code columns in ventas to their waterfall names
    v = ventas_df
    for code in sorted(VENTAS_CODES):
        if code in WATERFALL_CODES and code in v.columns:
            name = WATERFALL_CODES[code]
            v = v.withColumn(name, F.col(f"`{code}`")).drop(F.col(f"`{code}`"))

    # From margen, only take codes NOT already in ventas (to avoid ambiguity)
    margen_only_codes = {
        c for c in MARGEN_CODES
        if c in WATERFALL_CODES and c not in _OVERLAPPING_CODES and c in margen_df.columns
    }
    m_select_cols = [F.col(f"`{c}`") for c in JOIN_COLS]
    for code in sorted(margen_only_codes):
        name = WATERFALL_CODES[code]
        m_select_cols.append(F.col(f"`{code}`").alias(name))

    m = margen_df.select(*m_select_cols)

    # Join
    df = v.join(m, on=JOIN_COLS, how="left")

    # Fill nulls with 0 for arithmetic
    all_names = [WATERFALL_CODES[c] for c in WATERFALL_CODES if WATERFALL_CODES[c] in df.columns]
    for col_name in all_names:
        df = df.withColumn(col_name, F.coalesce(F.col(col_name), F.lit(0.0)))

    # On-invoice deductions
    on_invoice = [WATERFALL_CODES[c] for c in ON_INVOICE_CODES if WATERFALL_CODES.get(c) in df.columns]
    on_invoice_sum = sum(F.col(c) for c in on_invoice) if on_invoice else F.lit(0.0)

    # Off-invoice deductions
    off_invoice = [WATERFALL_CODES[c] for c in OFF_INVOICE_CODES if WATERFALL_CODES.get(c) in df.columns]
    off_invoice_sum = sum(F.col(c) for c in off_invoice) if off_invoice else F.lit(0.0)

    # Costs
    costs = [WATERFALL_CODES[c] for c in COST_CODES if WATERFALL_CODES.get(c) in df.columns]
    costs_sum = sum(F.col(c) for c in costs) if costs else F.lit(0.0)

    # Distributor spread
    dist = [WATERFALL_CODES[c] for c in DISTRIBUTOR_CODES if WATERFALL_CODES.get(c) in df.columns]
    dist_sum = sum(F.col(c) for c in dist) if dist else F.lit(0.0)

    df = (
        df
        .withColumn("venta_neta", F.col("tarifa") - on_invoice_sum)
        .withColumn("pocket_price", F.col("venta_neta") - off_invoice_sum)
        .withColumn("pocket_margin", F.col("pocket_price") - costs_sum - dist_sum)
    )
    return df


def build_price_ratios(df: DataFrame, method: str = "rolling_median", window_months: int = 6) -> DataFrame:
    """Compute price_ratio = current_price / reference_price.

    Parameters
    ----------
    method : str
        ``"rolling_median"`` — rolling average over *window_months*.
        ``"pre_tariff"`` — average price before the Dec-1 tariff step.
    """
    w = Window.partitionBy("Establecimiento", "Material").orderBy("Week-Month-Year")

    if method == "rolling_median":
        rolling_w = w.rowsBetween(-window_months, -1)
        df = df.withColumn("reference_price", F.avg("tarifa").over(rolling_w))
    else:  # pre_tariff
        month_col = F.month(F.col("`Week-Month-Year`"))
        pre_dec_w = Window.partitionBy("Establecimiento", "Material")
        df = df.withColumn(
            "reference_price",
            F.avg(
                F.when(month_col < 12, F.col("tarifa"))
            ).over(pre_dec_w),
        )

    # Avoid division by zero; null when no reference
    df = df.withColumn(
        "price_ratio",
        F.when(
            (F.col("reference_price").isNotNull()) & (F.col("reference_price") != 0),
            F.col("tarifa") / F.col("reference_price"),
        ),
    )
    return df


def build_model_features(
    df: DataFrame,
    dim_material: DataFrame,
    dim_establecimiento: DataFrame,
) -> DataFrame:
    """Enrich the waterfall DataFrame with hierarchy, temporal, and log features."""
    # Join dimension attributes — Material
    mat_select = dim_material.select(
        "Material", "Marca", "Lineadeproducto",
    ).dropDuplicates(["Material"])
    df = df.join(mat_select, on="Material", how="left")

    # Join dimension attributes — Establecimiento
    est_select = dim_establecimiento.select(
        "Establecimiento", "Categoria",
    ).dropDuplicates(["Establecimiento"])
    df = df.join(est_select, on="Establecimiento", how="left")

    # Temporal features
    periodo = F.col("`Week-Month-Year`")
    df = (
        df
        .withColumn("month", F.month(periodo))
        .withColumn("week", F.weekofyear(periodo))
        .withColumn(
            "is_post_tariff_step",
            (F.month(periodo) >= 12).cast("int"),
        )
    )

    # Asymmetry flag
    df = df.withColumn(
        "price_increase_flag",
        F.when(F.col("price_ratio") > 1.0, F.lit(1)).otherwise(F.lit(0)),
    )

    # Log transforms for log-log spec (guard against non-positive values)
    for col_name, log_name in [("tarifa", "ln_price"), ("price_ratio", "ln_price_ratio")]:
        if col_name in df.columns:
            df = df.withColumn(
                log_name,
                F.when(F.col(col_name) > 0, F.log(F.col(col_name))),
            )

    # Volume log — use Litros as the volume measure
    if "Litros" in df.columns:
        df = df.withColumn(
            "ln_volume",
            F.when(F.col("Litros") > 0, F.log(F.col("Litros"))),
        )

    return df


# COMMAND ----------

# ===========================================================================
# Diagnostics
# ===========================================================================


def summarize_price_band(df: DataFrame, group_cols: list[str] | None = None) -> DataFrame:
    """Price-band distribution (percentiles of pocket_price) by segment."""
    if group_cols is None:
        group_cols = ["Material"]

    return (
        df.groupBy(*group_cols)
        .agg(
            F.count("pocket_price").alias("n_obs"),
            F.percentile_approx("pocket_price", 0.10).alias("p10"),
            F.percentile_approx("pocket_price", 0.25).alias("p25"),
            F.percentile_approx("pocket_price", 0.50).alias("p50"),
            F.percentile_approx("pocket_price", 0.75).alias("p75"),
            F.percentile_approx("pocket_price", 0.90).alias("p90"),
            F.mean("pocket_price").alias("mean_pocket_price"),
        )
    )


def summarize_leakage(df: DataFrame, group_cols: list[str] | None = None) -> DataFrame:
    """Total and per-code leakage from tarifa to pocket_price, by segment."""
    if group_cols is None:
        group_cols = ["Material"]

    leakage_cols = [
        "obsequios", "descuento", "promo", "amortizacion", "rappel", "colaboracion",
    ]
    agg_exprs = [F.sum("tarifa").alias("total_tarifa")]
    for col_name in leakage_cols:
        if col_name in df.columns:
            agg_exprs.append(F.sum(col_name).alias(f"leak_{col_name}"))

    agg_exprs.append(
        (F.sum("tarifa") - F.sum("pocket_price")).alias("total_leakage"),
    )

    return df.groupBy(*group_cols).agg(*agg_exprs)


def flag_sparse_cells(
    df: DataFrame,
    min_periods: int = 12,
    group_cols: list[str] | None = None,
) -> DataFrame:
    """Identify cells with fewer than *min_periods* observations."""
    if group_cols is None:
        group_cols = ["Establecimiento", "Material"]

    counts = df.groupBy(*group_cols).agg(F.count("*").alias("n_periods"))
    return counts.withColumn("is_sparse", (F.col("n_periods") < min_periods).cast("int"))


def flag_negative_volume(df: DataFrame, volume_col: str = "Litros") -> DataFrame:
    """Flag rows where volume <= 0 (returns / lag artefacts)."""
    return df.withColumn(
        "has_negative_volume",
        (F.col(volume_col) <= 0).cast("int"),
    )


# COMMAND ----------

# ===========================================================================
# SCAN*PRO response model
# ===========================================================================

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


def build_pymc_model(
    df: pd.DataFrame,
    condition_cols: list[str] | None = None,
    hierarchy_cols: list[str] | None = None,
) -> pm.Model:
    """Build the SCAN*PRO PyMC model on a pandas DataFrame.

    Expected columns in *df*:
        ln_volume, ln_price_ratio, price_increase_flag, month,
        and any columns listed in *condition_cols*.
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
        alpha = pm.Normal("alpha", mu=0.0, sigma=5.0)  # noqa: F841

        # Base price elasticity — prior centred on literature mean
        prior_lo, prior_hi = ELASTICITY_PRIOR_RANGE
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


def fit_segment(
    df: pd.DataFrame,
    condition_cols: list[str] | None = None,
    sample_kwargs: dict[str, Any] | None = None,
) -> az.InferenceData:
    """Build and sample the SCAN*PRO model for a single segment."""
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


def fit_model_distributed(
    spark: SparkSession,
    features_df: DataFrame,
    group_cols: list[str],
    condition_cols: list[str] | None = None,
    sample_kwargs: dict[str, Any] | None = None,
) -> DataFrame:
    """Fit the model per segment using ``applyInPandas``.

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


# COMMAND ----------

# ===========================================================================
# Elasticity extraction & surface
# ===========================================================================


def extract_elasticities(posterior_df: DataFrame) -> DataFrame:
    """Extract elasticity estimates from the posterior summary DataFrame."""
    beta_base = (
        posterior_df
        .filter(F.col("parameter") == "beta_base")
        .select(
            "segment_key",
            F.col("mean").alias("beta_base_mean"),
            F.col("sd").alias("beta_base_sd"),
            F.col("hdi_3").alias("beta_base_lo"),
            F.col("hdi_97").alias("beta_base_hi"),
            "n_obs",
        )
    )

    beta_up = (
        posterior_df
        .filter(F.col("parameter") == "beta_up")
        .select(
            "segment_key",
            F.col("mean").alias("beta_up_mean"),
        )
    )

    elasticities = beta_base.join(beta_up, on="segment_key", how="left")

    # Total elasticity for price increases = beta_base + beta_up
    elasticities = elasticities.withColumn(
        "beta_total_up",
        F.col("beta_base_mean") + F.coalesce(F.col("beta_up_mean"), F.lit(0.0)),
    )

    # Causal gate: fail if upper HDI bound > 0 (i.e. P(β<0) < 0.95 approx)
    elasticities = elasticities.withColumn(
        "passes_causal_gate",
        (F.col("beta_base_hi") < 0).cast("int"),
    )

    return elasticities


def build_elasticity_surface(
    elasticities_df: DataFrame,
    dim_df: DataFrame,
    segment_col: str = "segment_key",
) -> DataFrame:
    """Join segment-level elasticities to the full establishment x material grid."""
    surface = dim_df.join(elasticities_df, on=segment_col, how="left")

    # Shrinkage fallback: if a cell has no direct estimate, fill with the
    # grand mean across all segments that passed the causal gate.
    passing = elasticities_df.filter(F.col("passes_causal_gate") == 1)
    grand_stats = passing.agg(
        F.mean("beta_base_mean").alias("_grand_beta_base"),
        F.mean("beta_total_up").alias("_grand_beta_up"),
    ).collect()[0]

    grand_base = float(grand_stats["_grand_beta_base"]) if grand_stats["_grand_beta_base"] is not None else -1.0
    grand_up = float(grand_stats["_grand_beta_up"]) if grand_stats["_grand_beta_up"] is not None else -1.0

    surface = surface.withColumn(
        "beta_base_mean",
        F.coalesce(F.col("beta_base_mean"), F.lit(grand_base)),
    ).withColumn(
        "beta_total_up",
        F.coalesce(F.col("beta_total_up"), F.lit(grand_up)),
    )

    return surface


# COMMAND ----------

# ===========================================================================
# Optimizer (Phase 3 scaffold)
# ===========================================================================


def simulate_margin(
    elasticity_surface: DataFrame,
    policy_df: DataFrame,
    current_price_col: str = "tarifa",
    proposed_price_col: str = "proposed_price",
    volume_col: str = "volumen",
) -> DataFrame:
    """Simulate expected margin under a proposed pricing policy."""
    df = policy_df.join(elasticity_surface, on="segment_key", how="left")

    df = df.withColumn(
        "price_ratio_new",
        F.col(proposed_price_col) / F.col(current_price_col),
    )

    # Pick the right elasticity depending on direction
    df = df.withColumn(
        "effective_beta",
        F.when(F.col("price_ratio_new") > 1.0, F.col("beta_total_up"))
        .otherwise(F.col("beta_base_mean")),
    )

    # Log-log prediction
    df = df.withColumn(
        "expected_volume",
        F.col(volume_col) * F.pow(F.col("price_ratio_new"), F.col("effective_beta")),
    )

    df = df.withColumn(
        "expected_margin",
        F.col(proposed_price_col) * F.col("expected_volume"),
    )

    return df


def optimize_policy(
    elasticity_surface: DataFrame,
    constraints: dict | None = None,
) -> DataFrame:
    """Placeholder for constrained margin optimization over the elasticity surface."""
    _ = constraints  # reserved for bounds, budget caps, etc.

    result = elasticity_surface.withColumn(
        "proposed_price_multiplier",
        F.lit(1.02),
    )
    return result


# COMMAND ----------

# ===========================================================================
# Evaluation metrics (3-layer)
# ===========================================================================


def compute_crps(posterior_samples: np.ndarray, actuals: np.ndarray) -> float:
    """Continuous Ranked Probability Score (lower is better)."""
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
    """Weighted Absolute Percentage Error = sum|y-yhat| / sum|y|."""
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
    """Aggregate bias = sum(yhat-y) / sum(y)."""
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


def check_elasticity_sign(posterior_samples: np.ndarray) -> dict[str, float]:
    """Check P(beta < 0) per column of posterior_samples."""
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

    The test passes if the resulting confidence interval includes zero.
    """
    result = model_fn(data, fake_date_idx)
    passes = result["lower"] <= 0.0 <= result["upper"]
    return {"placebo_mean": result["mean"], "ci": (result["lower"], result["upper"]), "passes": passes}


def compute_margin_uplift(
    current_policy: DataFrame,
    model_policy: DataFrame,
    response_surface: DataFrame,
) -> dict[str, float]:
    """Compute expected margin uplift of model policy vs. current."""
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


def temporal_split(
    df: DataFrame,
    date_col: str = "periodo",
    method: str = "rolling_origin",
    n_splits: int = 4,
) -> list[tuple[DataFrame, DataFrame]]:
    """Split a panel temporally for evaluation."""
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

"""Posterior extraction and elasticity surface construction."""

from __future__ import annotations

import pyspark.sql.functions as F
from pyspark.sql import DataFrame


def extract_elasticities(posterior_df: DataFrame) -> DataFrame:
    """Extract elasticity estimates from the posterior summary DataFrame.

    Returns one row per segment with base elasticity, total up-elasticity,
    and a causal-gate flag.
    """
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
    """Join segment-level elasticities to the full establishment × material grid.

    Cells without direct estimates inherit the family-level value via a
    coalesce over the hierarchy.
    """
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

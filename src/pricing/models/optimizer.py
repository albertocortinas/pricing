"""Phase 3 scaffold: margin simulation and policy optimization."""

from __future__ import annotations

import pyspark.sql.functions as F
from pyspark.sql import DataFrame


def simulate_margin(
    elasticity_surface: DataFrame,
    policy_df: DataFrame,
    current_price_col: str = "tarifa",
    proposed_price_col: str = "proposed_price",
    volume_col: str = "volumen",
) -> DataFrame:
    """Simulate expected margin under a proposed pricing policy.

    Uses the log-log response surface:
        ln(q_new) = ln(q_base) + β · ln(p_new / p_base)

    Parameters
    ----------
    elasticity_surface : DataFrame
        Must contain ``beta_base_mean`` and ``beta_total_up`` per segment.
    policy_df : DataFrame
        Must contain segment keys, current price, proposed price, and base volume.
    """
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
    """Placeholder for constrained margin optimization over the elasticity surface.

    Full implementation in Phase 3. Current version returns the input surface
    with a naive +2% price increase as the "proposed" policy.
    """
    _ = constraints  # reserved for bounds, budget caps, etc.

    result = elasticity_surface.withColumn(
        "proposed_price_multiplier",
        F.lit(1.02),
    )
    return result

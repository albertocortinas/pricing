"""Phase 1 diagnostic aggregations on the pocket-price waterfall."""

from __future__ import annotations

import pyspark.sql.functions as F
from pyspark.sql import DataFrame


def summarize_price_band(df: DataFrame, group_cols: list[str] | None = None) -> DataFrame:
    """Price-band distribution (percentiles of pocket_price) by segment.

    Parameters
    ----------
    group_cols : list[str] | None
        Columns defining the segment (e.g. ["Marca", "Categoria"]).
        Defaults to ``["material"]``.
    """
    if group_cols is None:
        group_cols = ["material"]

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
        group_cols = ["material"]

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
        group_cols = ["establecimiento", "material"]

    counts = df.groupBy(*group_cols).agg(F.count("*").alias("n_periods"))
    return counts.withColumn("is_sparse", (F.col("n_periods") < min_periods).cast("int"))


def flag_negative_volume(df: DataFrame, volume_col: str = "volumen") -> DataFrame:
    """Flag rows where volume <= 0 (returns / lag artefacts)."""
    return df.withColumn(
        "has_negative_volume",
        (F.col(volume_col) <= 0).cast("int"),
    )

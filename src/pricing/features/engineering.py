"""Feature engineering for the pricing waterfall and SCAN*PRO model."""

from __future__ import annotations

import pyspark.sql.functions as F
from pyspark.sql import DataFrame, Window

from pricing import config


# ---------------------------------------------------------------------------
# Step 2a — Pocket price waterfall
# ---------------------------------------------------------------------------

def build_pocket_price_waterfall(ventas_df: DataFrame, margen_df: DataFrame) -> DataFrame:
    """Join ventas + margen and compute the pocket-price waterfall.

    Returns a DataFrame with one row per (establecimiento, material, periodo,
    distribuidor) and named columns for each waterfall component plus computed
    aggregates: venta_neta, pocket_price, pocket_margin.
    """
    join_cols = ["establecimiento", "material", "periodo", "distribuidor"]

    # Pivot waterfall codes into named columns from ventas
    ventas_pivot = _pivot_codes(ventas_df, config.VENTAS_CODES, join_cols)
    # Pivot waterfall codes into named columns from margen
    margen_pivot = _pivot_codes(margen_df, config.MARGEN_CODES, join_cols)

    df = ventas_pivot.join(margen_pivot, on=join_cols, how="outer")

    # Fill nulls with 0 for arithmetic
    code_cols = [config.WATERFALL_CODES[c] for c in config.WATERFALL_CODES]
    for col_name in code_cols:
        if col_name in df.columns:
            df = df.withColumn(col_name, F.coalesce(F.col(col_name), F.lit(0.0)))

    # On-invoice deductions
    on_invoice = [config.WATERFALL_CODES[c] for c in config.ON_INVOICE_CODES if c in config.WATERFALL_CODES]
    on_invoice_sum = sum(F.col(c) for c in on_invoice) if on_invoice else F.lit(0.0)

    # Off-invoice deductions
    off_invoice = [config.WATERFALL_CODES[c] for c in config.OFF_INVOICE_CODES if c in config.WATERFALL_CODES]
    off_invoice_sum = sum(F.col(c) for c in off_invoice) if off_invoice else F.lit(0.0)

    # Costs
    costs = [config.WATERFALL_CODES[c] for c in config.COST_CODES if c in config.WATERFALL_CODES]
    costs_sum = sum(F.col(c) for c in costs) if costs else F.lit(0.0)

    # Distributor spread
    dist = [config.WATERFALL_CODES[c] for c in config.DISTRIBUTOR_CODES if c in config.WATERFALL_CODES]
    dist_sum = sum(F.col(c) for c in dist) if dist else F.lit(0.0)

    df = (
        df
        .withColumn("venta_neta", F.col("tarifa") - on_invoice_sum)
        .withColumn("pocket_price", F.col("venta_neta") - off_invoice_sum)
        .withColumn("pocket_margin", F.col("pocket_price") - costs_sum - dist_sum)
    )
    return df


def _pivot_codes(df: DataFrame, code_set: set[str], join_cols: list[str]) -> DataFrame:
    """Pivot a fact table from long to wide using waterfall code mappings.

    Expects the input DataFrame to have columns: join_cols + [codigo, importe].
    """
    # Map code → name; filter to relevant codes
    code_name_map = {c: config.WATERFALL_CODES[c] for c in code_set if c in config.WATERFALL_CODES}
    if not code_name_map:
        return df.select(*join_cols).dropDuplicates()

    mapping_expr = F.create_map([F.lit(x) for pair in code_name_map.items() for x in pair])
    filtered = df.filter(F.col("codigo").isin(list(code_name_map.keys())))
    filtered = filtered.withColumn("nombre", mapping_expr[F.col("codigo")])

    pivoted = (
        filtered
        .groupBy(*join_cols)
        .pivot("nombre", list(code_name_map.values()))
        .agg(F.sum("importe"))
    )
    return pivoted


# ---------------------------------------------------------------------------
# Step 2b — Price ratios (SCAN*PRO price variable)
# ---------------------------------------------------------------------------

def build_price_ratios(df: DataFrame, method: str = "rolling_median", window_months: int = 6) -> DataFrame:
    """Compute price_ratio = current_price / reference_price.

    Parameters
    ----------
    method : str
        ``"rolling_median"`` — rolling median over *window_months*.
        ``"pre_tariff"`` — median price before the Dec-1 tariff step.
    """
    w = Window.partitionBy("establecimiento", "material").orderBy("periodo")

    if method == "rolling_median":
        # Use avg as a window-compatible approximation (median not supported in Spark window frames)
        rolling_w = w.rowsBetween(-window_months, -1)
        df = df.withColumn("reference_price", F.avg("tarifa").over(rolling_w))
    else:  # pre_tariff
        # Median of pre-December prices as reference
        month_col = F.month(F.col("periodo"))
        pre_dec_w = Window.partitionBy("establecimiento", "material")
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


# ---------------------------------------------------------------------------
# Step 2c — Full model features
# ---------------------------------------------------------------------------

def build_model_features(
    df: DataFrame,
    dim_material: DataFrame,
    dim_establecimiento: DataFrame,
) -> DataFrame:
    """Enrich the waterfall DataFrame with hierarchy, temporal, and log features."""
    # Join dimension attributes
    mat_cols = ["material", "Marca", "Lineadeproducto"]
    mat_select = dim_material.select(
        F.col("Material").alias("material"),
        *[F.col(c) for c in mat_cols[1:]],
    ).dropDuplicates(["material"])
    df = df.join(mat_select, on="material", how="left")

    est_cols = ["establecimiento", "Categoria", "Provincia"]
    est_select = dim_establecimiento.select(
        F.col("Establecimiento").alias("establecimiento"),
        *[F.col(c) for c in est_cols[1:]],
    ).dropDuplicates(["establecimiento"])
    df = df.join(est_select, on="establecimiento", how="left")

    # Temporal features
    df = (
        df
        .withColumn("month", F.month("periodo"))
        .withColumn("week", F.weekofyear("periodo"))
        .withColumn(
            "is_post_tariff_step",
            (F.month("periodo") >= 12).cast("int"),
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
    # Volume log (assumes a "volumen" column exists)
    if "volumen" in df.columns:
        df = df.withColumn(
            "ln_volume",
            F.when(F.col("volumen") > 0, F.log(F.col("volumen"))),
        )

    return df

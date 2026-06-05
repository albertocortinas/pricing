"""Feature engineering for the pricing waterfall and SCAN*PRO model.

The source tables are already in wide format: waterfall codes (050, 210, etc.)
are column names, not row values.
"""

from __future__ import annotations

import pyspark.sql.functions as F
from pyspark.sql import DataFrame, Window

from pricing import config

# Canonical join keys matching the real schema
JOIN_COLS = ["Establecimiento", "Material", "Week-Month-Year", "Distribuidor"]

# Codes that appear in BOTH ventas and margen — use ventas as source of truth
_OVERLAPPING_CODES = {"100", "210", "300", "420", "740"}


# ---------------------------------------------------------------------------
# Pocket price waterfall
# ---------------------------------------------------------------------------

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
    for code in sorted(config.VENTAS_CODES):
        if code in config.WATERFALL_CODES and code in v.columns:
            name = config.WATERFALL_CODES[code]
            v = v.withColumn(name, F.col(f"`{code}`")).drop(F.col(f"`{code}`"))

    # From margen, only take codes NOT already in ventas (to avoid ambiguity)
    margen_only_codes = {
        c for c in config.MARGEN_CODES
        if c in config.WATERFALL_CODES and c not in _OVERLAPPING_CODES and c in margen_df.columns
    }
    m_select_cols = [F.col(f"`{c}`") for c in JOIN_COLS]
    for code in sorted(margen_only_codes):
        name = config.WATERFALL_CODES[code]
        m_select_cols.append(F.col(f"`{code}`").alias(name))

    m = margen_df.select(*m_select_cols)

    # Join
    df = v.join(m, on=JOIN_COLS, how="left")

    # Fill nulls with 0 for arithmetic
    all_names = [config.WATERFALL_CODES[c] for c in config.WATERFALL_CODES if config.WATERFALL_CODES[c] in df.columns]
    for col_name in all_names:
        df = df.withColumn(col_name, F.coalesce(F.col(col_name), F.lit(0.0)))

    # On-invoice deductions
    on_invoice = [config.WATERFALL_CODES[c] for c in config.ON_INVOICE_CODES if config.WATERFALL_CODES.get(c) in df.columns]
    on_invoice_sum = sum(F.col(c) for c in on_invoice) if on_invoice else F.lit(0.0)

    # Off-invoice deductions
    off_invoice = [config.WATERFALL_CODES[c] for c in config.OFF_INVOICE_CODES if config.WATERFALL_CODES.get(c) in df.columns]
    off_invoice_sum = sum(F.col(c) for c in off_invoice) if off_invoice else F.lit(0.0)

    # Costs
    costs = [config.WATERFALL_CODES[c] for c in config.COST_CODES if config.WATERFALL_CODES.get(c) in df.columns]
    costs_sum = sum(F.col(c) for c in costs) if costs else F.lit(0.0)

    # Distributor spread
    dist = [config.WATERFALL_CODES[c] for c in config.DISTRIBUTOR_CODES if config.WATERFALL_CODES.get(c) in df.columns]
    dist_sum = sum(F.col(c) for c in dist) if dist else F.lit(0.0)

    df = (
        df
        .withColumn("venta_neta", F.col("tarifa") - on_invoice_sum)
        .withColumn("pocket_price", F.col("venta_neta") - off_invoice_sum)
        .withColumn("pocket_margin", F.col("pocket_price") - costs_sum - dist_sum)
    )
    return df


# ---------------------------------------------------------------------------
# Price ratios (SCAN*PRO price variable)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Full model features
# ---------------------------------------------------------------------------

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

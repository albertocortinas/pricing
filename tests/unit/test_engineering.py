"""Tests for feature engineering functions."""

import math
from datetime import date

import pyspark.sql.functions as F
from pyspark.sql import SparkSession, Window
from pyspark.sql.types import DateType, DoubleType, StringType, StructField, StructType

# ---------------------------------------------------------------------------
# Inline config constants needed by the functions under test
# ---------------------------------------------------------------------------
WATERFALL_CODES = {
    "050": "tarifa", "100": "obsequios", "210": "descuento", "300": "promo",
    "420": "amortizacion", "740": "rappel",
    "858": "impuestos_especiales", "859": "ecotasa_punto_verde",
    "861": "coste_logistico", "890": "coste_producto",
    "954": "mano_obra_ib", "956": "amortizacion_ib",
    "900": "tarifa_distribuidor", "901": "impuestos_distribuidor",
    "902": "pa_distribuidor", "920": "colaboracion",
}
VENTAS_CODES = {"050", "100", "210", "300", "420", "740", "100_agua"}
MARGEN_CODES = set(WATERFALL_CODES.keys()) - VENTAS_CODES | {
    "120_agua", "140_agua", "160_agua", "170_agua", "180_agua", "190_agua",
}
ON_INVOICE_CODES = {"100", "210", "300", "420", "740"}
OFF_INVOICE_CODES = {"920"}
COST_CODES = {"858", "859", "861", "890", "954", "956"}
DISTRIBUTOR_CODES = {"900", "901", "902"}

JOIN_COLS = ["Establecimiento", "Material", "Week-Month-Year", "Distribuidor"]
_OVERLAPPING_CODES = {"100", "210", "300", "420", "740"}


# ---------------------------------------------------------------------------
# Inline functions under test
# ---------------------------------------------------------------------------
def build_pocket_price_waterfall(ventas_df, margen_df):
    v = ventas_df
    for code in sorted(VENTAS_CODES):
        if code in WATERFALL_CODES and code in v.columns:
            name = WATERFALL_CODES[code]
            v = v.withColumn(name, F.col(f"`{code}`")).drop(F.col(f"`{code}`"))

    margen_only_codes = {
        c for c in MARGEN_CODES
        if c in WATERFALL_CODES and c not in _OVERLAPPING_CODES and c in margen_df.columns
    }
    m_select_cols = [F.col(f"`{c}`") for c in JOIN_COLS]
    for code in sorted(margen_only_codes):
        name = WATERFALL_CODES[code]
        m_select_cols.append(F.col(f"`{code}`").alias(name))

    m = margen_df.select(*m_select_cols)
    df = v.join(m, on=JOIN_COLS, how="left")

    all_names = [WATERFALL_CODES[c] for c in WATERFALL_CODES if WATERFALL_CODES[c] in df.columns]
    for col_name in all_names:
        df = df.withColumn(col_name, F.coalesce(F.col(col_name), F.lit(0.0)))

    on_invoice = [WATERFALL_CODES[c] for c in ON_INVOICE_CODES if WATERFALL_CODES.get(c) in df.columns]
    on_invoice_sum = sum(F.col(c) for c in on_invoice) if on_invoice else F.lit(0.0)

    off_invoice = [WATERFALL_CODES[c] for c in OFF_INVOICE_CODES if WATERFALL_CODES.get(c) in df.columns]
    off_invoice_sum = sum(F.col(c) for c in off_invoice) if off_invoice else F.lit(0.0)

    costs = [WATERFALL_CODES[c] for c in COST_CODES if WATERFALL_CODES.get(c) in df.columns]
    costs_sum = sum(F.col(c) for c in costs) if costs else F.lit(0.0)

    dist = [WATERFALL_CODES[c] for c in DISTRIBUTOR_CODES if WATERFALL_CODES.get(c) in df.columns]
    dist_sum = sum(F.col(c) for c in dist) if dist else F.lit(0.0)

    df = (
        df
        .withColumn("venta_neta", F.col("tarifa") - on_invoice_sum)
        .withColumn("pocket_price", F.col("venta_neta") - off_invoice_sum)
        .withColumn("pocket_margin", F.col("pocket_price") - costs_sum - dist_sum)
    )
    return df


def build_price_ratios(df, method="rolling_median", window_months=6):
    w = Window.partitionBy("Establecimiento", "Material").orderBy("Week-Month-Year")

    if method == "rolling_median":
        rolling_w = w.rowsBetween(-window_months, -1)
        df = df.withColumn("reference_price", F.avg("tarifa").over(rolling_w))
    else:
        month_col = F.month(F.col("`Week-Month-Year`"))
        pre_dec_w = Window.partitionBy("Establecimiento", "Material")
        df = df.withColumn(
            "reference_price",
            F.avg(F.when(month_col < 12, F.col("tarifa"))).over(pre_dec_w),
        )

    df = df.withColumn(
        "price_ratio",
        F.when(
            (F.col("reference_price").isNotNull()) & (F.col("reference_price") != 0),
            F.col("tarifa") / F.col("reference_price"),
        ),
    )
    return df


def build_model_features(df, dim_material, dim_establecimiento):
    mat_select = dim_material.select("Material", "Marca", "Lineadeproducto").dropDuplicates(["Material"])
    df = df.join(mat_select, on="Material", how="left")

    est_select = dim_establecimiento.select("Establecimiento", "Categoria").dropDuplicates(["Establecimiento"])
    df = df.join(est_select, on="Establecimiento", how="left")

    periodo = F.col("`Week-Month-Year`")
    df = (
        df
        .withColumn("month", F.month(periodo))
        .withColumn("week", F.weekofyear(periodo))
        .withColumn("is_post_tariff_step", (F.month(periodo) >= 12).cast("int"))
    )

    df = df.withColumn(
        "price_increase_flag",
        F.when(F.col("price_ratio") > 1.0, F.lit(1)).otherwise(F.lit(0)),
    )

    for col_name, log_name in [("tarifa", "ln_price"), ("price_ratio", "ln_price_ratio")]:
        if col_name in df.columns:
            df = df.withColumn(log_name, F.when(F.col(col_name) > 0, F.log(F.col(col_name))))

    if "Litros" in df.columns:
        df = df.withColumn("ln_volume", F.when(F.col("Litros") > 0, F.log(F.col("Litros"))))

    return df


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_build_pocket_price_waterfall(spark: SparkSession):
    ventas_schema = StructType([
        StructField("Establecimiento", StringType()),
        StructField("Material", StringType()),
        StructField("Week-Month-Year", DateType()),
        StructField("Distribuidor", StringType()),
        StructField("VentaNeta", DoubleType()),
        StructField("Litros", DoubleType()),
        StructField("050", DoubleType()),
        StructField("100", DoubleType()),
        StructField("210", DoubleType()),
        StructField("300", DoubleType()),
        StructField("420", DoubleType()),
        StructField("740", DoubleType()),
    ])
    ventas_rows = [
        ("E1", "M1", date(2024, 1, 1), "D1", 92.0, 50.0, 100.0, 0.0, 5.0, 3.0, 0.0, 0.0),
        ("E1", "M1", date(2024, 2, 1), "D1", 98.0, 60.0, 110.0, 0.0, 6.0, 4.0, 0.0, 2.0),
    ]
    ventas_df = spark.createDataFrame(ventas_rows, ventas_schema)

    margen_schema = StructType([
        StructField("Establecimiento", StringType()),
        StructField("Material", StringType()),
        StructField("Week-Month-Year", DateType()),
        StructField("Distribuidor", StringType()),
        StructField("890", DoubleType()),
        StructField("900", DoubleType()),
        StructField("858", DoubleType()),
        StructField("861", DoubleType()),
    ])
    margen_rows = [
        ("E1", "M1", date(2024, 1, 1), "D1", 20.0, 10.0, 2.0, 3.0),
        ("E1", "M1", date(2024, 2, 1), "D1", 22.0, 11.0, 2.5, 3.5),
    ]
    margen_df = spark.createDataFrame(margen_rows, margen_schema)

    result = build_pocket_price_waterfall(ventas_df, margen_df)
    rows = result.orderBy("`Week-Month-Year`").collect()

    assert len(rows) == 2

    r = rows[0]
    assert r["tarifa"] == 100.0
    assert r["venta_neta"] == 100.0 - 8.0  # 92.0
    assert r["pocket_price"] == 92.0


def test_build_price_ratios(spark: SparkSession):
    schema = StructType([
        StructField("Establecimiento", StringType()),
        StructField("Material", StringType()),
        StructField("Week-Month-Year", DateType()),
        StructField("tarifa", DoubleType()),
    ])
    rows = [
        ("E1", "M1", date(2024, 1, 1), 100.0),
        ("E1", "M1", date(2024, 2, 1), 100.0),
        ("E1", "M1", date(2024, 3, 1), 110.0),
        ("E1", "M1", date(2024, 4, 1), 105.0),
    ]
    df = spark.createDataFrame(rows, schema)
    result = build_price_ratios(df, method="rolling_median")
    collected = result.orderBy("`Week-Month-Year`").collect()

    assert collected[0]["price_ratio"] is None
    assert abs(collected[2]["price_ratio"] - 1.1) < 0.01


def test_build_model_features_log_transform(spark: SparkSession):
    schema = StructType([
        StructField("Establecimiento", StringType()),
        StructField("Material", StringType()),
        StructField("Week-Month-Year", DateType()),
        StructField("tarifa", DoubleType()),
        StructField("price_ratio", DoubleType()),
        StructField("Litros", DoubleType()),
    ])
    rows = [("E1", "M1", date(2024, 6, 15), 100.0, 1.1, 50.0)]
    df = spark.createDataFrame(rows, schema)

    dim_mat = spark.createDataFrame(
        [("M1", "Premium", "Cerveza")],
        ["Material", "Marca", "Lineadeproducto"],
    )
    dim_est = spark.createDataFrame(
        [("E1", "Bar")],
        ["Establecimiento", "Categoria"],
    )

    result = build_model_features(df, dim_mat, dim_est)
    row = result.collect()[0]

    assert row["month"] == 6
    assert row["is_post_tariff_step"] == 0
    assert row["price_increase_flag"] == 1
    assert abs(row["ln_price_ratio"] - math.log(1.1)) < 0.001
    assert abs(row["ln_volume"] - math.log(50.0)) < 0.001
    assert row["Marca"] == "Premium"
    assert row["Categoria"] == "Bar"

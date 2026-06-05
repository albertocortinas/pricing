"""Tests for feature engineering functions."""

import math
from datetime import date

from pyspark.sql import SparkSession
from pyspark.sql.types import DateType, DoubleType, StringType, StructField, StructType


def test_build_pocket_price_waterfall(spark: SparkSession):
    from pricing.features.engineering import build_pocket_price_waterfall

    # Ventas: wide format with code columns (050, 100, 210, 300, 420, 740)
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

    # Margen: wide format with cost/distributor code columns
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
    # tarifa = 050 = 100, on_invoice = 100+210+300+420+740 = 0+5+3+0+0 = 8
    assert r["tarifa"] == 100.0
    assert r["venta_neta"] == 100.0 - 8.0  # 92.0
    # pocket_price = venta_neta - off_invoice (colaboracion=0) = 92.0
    assert r["pocket_price"] == 92.0


def test_build_price_ratios(spark: SparkSession):
    from pricing.features.engineering import build_price_ratios

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

    # First row has no prior data -> null reference
    assert collected[0]["price_ratio"] is None
    # Third row: reference = avg of [100, 100] = 100, ratio = 110/100 = 1.1
    assert abs(collected[2]["price_ratio"] - 1.1) < 0.01


def test_build_model_features_log_transform(spark: SparkSession):
    from pricing.features.engineering import build_model_features

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

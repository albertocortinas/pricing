"""Tests for feature engineering functions."""

import math

import pytest
from pyspark.sql import SparkSession
from pyspark.sql.types import DoubleType, StringType, StructField, StructType, DateType
from datetime import date


@pytest.fixture
def ventas_df(spark: SparkSession):
    """Synthetic ventas fact table in long format (codigo, importe)."""
    schema = StructType([
        StructField("establecimiento", StringType()),
        StructField("material", StringType()),
        StructField("periodo", DateType()),
        StructField("distribuidor", StringType()),
        StructField("codigo", StringType()),
        StructField("importe", DoubleType()),
    ])
    rows = [
        # Tarifa
        ("E1", "M1", date(2024, 1, 1), "D1", "050", 100.0),
        ("E1", "M1", date(2024, 2, 1), "D1", "050", 110.0),
        # Descuento
        ("E1", "M1", date(2024, 1, 1), "D1", "210", 5.0),
        ("E1", "M1", date(2024, 2, 1), "D1", "210", 6.0),
        # Promo
        ("E1", "M1", date(2024, 1, 1), "D1", "300", 3.0),
        ("E1", "M1", date(2024, 2, 1), "D1", "300", 4.0),
    ]
    return spark.createDataFrame(rows, schema)


@pytest.fixture
def margen_df(spark: SparkSession):
    """Synthetic margen fact table."""
    schema = StructType([
        StructField("establecimiento", StringType()),
        StructField("material", StringType()),
        StructField("periodo", DateType()),
        StructField("distribuidor", StringType()),
        StructField("codigo", StringType()),
        StructField("importe", DoubleType()),
    ])
    rows = [
        # Coste producto
        ("E1", "M1", date(2024, 1, 1), "D1", "890", 20.0),
        ("E1", "M1", date(2024, 2, 1), "D1", "890", 22.0),
        # Tarifa distribuidor
        ("E1", "M1", date(2024, 1, 1), "D1", "900", 10.0),
        ("E1", "M1", date(2024, 2, 1), "D1", "900", 11.0),
    ]
    return spark.createDataFrame(rows, schema)


def test_build_pocket_price_waterfall(spark, ventas_df, margen_df):
    from pricing.features.engineering import build_pocket_price_waterfall

    result = build_pocket_price_waterfall(ventas_df, margen_df)
    rows = result.orderBy("periodo").collect()

    assert len(rows) == 2

    # First row: tarifa=100, descuento=5, promo=3, coste=20, dist=10
    r = rows[0]
    assert r["tarifa"] == 100.0
    assert r["descuento"] == 5.0
    # venta_neta = tarifa - on_invoice (obsequios+descuento+promo+amortizacion+rappel)
    # on_invoice for this row = 0 + 5 + 3 + 0 + 0 = 8
    assert r["venta_neta"] == 100.0 - 8.0  # 92.0
    # pocket_price = venta_neta - off_invoice (colaboracion=0)
    assert r["pocket_price"] == 92.0


def test_build_price_ratios(spark):
    from pricing.features.engineering import build_price_ratios

    schema = StructType([
        StructField("establecimiento", StringType()),
        StructField("material", StringType()),
        StructField("periodo", DateType()),
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
    collected = result.orderBy("periodo").collect()

    # First row has no prior data → null reference
    assert collected[0]["price_ratio"] is None
    # Third row: reference = median of [100, 100] = 100, ratio = 110/100 = 1.1
    assert abs(collected[2]["price_ratio"] - 1.1) < 0.01


def test_build_model_features_log_transform(spark):
    from pricing.features.engineering import build_model_features

    schema = StructType([
        StructField("establecimiento", StringType()),
        StructField("material", StringType()),
        StructField("periodo", DateType()),
        StructField("tarifa", DoubleType()),
        StructField("price_ratio", DoubleType()),
        StructField("volumen", DoubleType()),
    ])
    rows = [("E1", "M1", date(2024, 6, 15), 100.0, 1.1, 50.0)]
    df = spark.createDataFrame(rows, schema)

    dim_mat = spark.createDataFrame(
        [("M1", "Cerveza", "Premium")],
        ["Material", "Lineadeproducto", "Marca"],
    )
    dim_est = spark.createDataFrame(
        [("E1", "Bar", "Barcelona")],
        ["Establecimiento", "Categoria", "Provincia"],
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

"""Tests for diagnostic functions."""

from datetime import date

import pyspark.sql.functions as F
from pyspark.sql import SparkSession
from pyspark.sql.types import DateType, DoubleType, StringType, StructField, StructType

import pytest


# ---------------------------------------------------------------------------
# Inline functions under test
# ---------------------------------------------------------------------------
def summarize_price_band(df, group_cols=None):
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


def flag_sparse_cells(df, min_periods=12, group_cols=None):
    if group_cols is None:
        group_cols = ["Establecimiento", "Material"]
    counts = df.groupBy(*group_cols).agg(F.count("*").alias("n_periods"))
    return counts.withColumn("is_sparse", (F.col("n_periods") < min_periods).cast("int"))


def flag_negative_volume(df, volume_col="Litros"):
    return df.withColumn("has_negative_volume", (F.col(volume_col) <= 0).cast("int"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def waterfall_df(spark: SparkSession):
    """Synthetic waterfall DataFrame matching real column names."""
    schema = StructType([
        StructField("Establecimiento", StringType()),
        StructField("Material", StringType()),
        StructField("Week-Month-Year", DateType()),
        StructField("tarifa", DoubleType()),
        StructField("descuento", DoubleType()),
        StructField("pocket_price", DoubleType()),
        StructField("Litros", DoubleType()),
    ])
    rows = [
        ("E1", "M1", date(2024, 1, 1), 100.0, 5.0, 90.0, 50.0),
        ("E1", "M1", date(2024, 2, 1), 100.0, 5.0, 90.0, 60.0),
        ("E1", "M1", date(2024, 3, 1), 100.0, 5.0, 90.0, -10.0),
        ("E2", "M2", date(2024, 1, 1), 80.0, 3.0, 72.0, 30.0),
    ]
    return spark.createDataFrame(rows, schema)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_flag_sparse_cells(spark, waterfall_df):
    result = flag_sparse_cells(waterfall_df, min_periods=3)
    rows = {(r["Establecimiento"], r["Material"]): r for r in result.collect()}

    assert rows[("E1", "M1")]["is_sparse"] == 0
    assert rows[("E2", "M2")]["is_sparse"] == 1


def test_flag_negative_volume(spark, waterfall_df):
    result = flag_negative_volume(waterfall_df)
    flagged = result.filter("has_negative_volume = 1").collect()
    assert len(flagged) == 1
    assert flagged[0]["Litros"] == -10.0


def test_summarize_price_band(spark, waterfall_df):
    result = summarize_price_band(waterfall_df, group_cols=["Material"])
    rows = {r["Material"]: r for r in result.collect()}
    assert rows["M1"]["n_obs"] == 3
    assert rows["M1"]["p50"] == 90.0
    assert rows["M2"]["n_obs"] == 1

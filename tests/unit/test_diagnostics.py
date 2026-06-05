"""Tests for diagnostic functions."""

from datetime import date

from pyspark.sql import SparkSession
from pyspark.sql.types import DoubleType, StringType, StructField, StructType, DateType


@__import__("pytest").fixture
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


def test_flag_sparse_cells(spark, waterfall_df):
    from pricing.diagnostics.waterfall import flag_sparse_cells

    result = flag_sparse_cells(waterfall_df, min_periods=3)
    rows = {(r["Establecimiento"], r["Material"]): r for r in result.collect()}

    # E1, M1 has 3 observations -> not sparse (min=3)
    assert rows[("E1", "M1")]["is_sparse"] == 0
    # E2, M2 has 1 observation -> sparse
    assert rows[("E2", "M2")]["is_sparse"] == 1


def test_flag_negative_volume(spark, waterfall_df):
    from pricing.diagnostics.waterfall import flag_negative_volume

    result = flag_negative_volume(waterfall_df)
    flagged = result.filter("has_negative_volume = 1").collect()
    assert len(flagged) == 1
    assert flagged[0]["Litros"] == -10.0


def test_summarize_price_band(spark, waterfall_df):
    from pricing.diagnostics.waterfall import summarize_price_band

    result = summarize_price_band(waterfall_df, group_cols=["Material"])
    rows = {r["Material"]: r for r in result.collect()}
    assert rows["M1"]["n_obs"] == 3
    assert rows["M1"]["p50"] == 90.0
    assert rows["M2"]["n_obs"] == 1

def test_import():
    import pricing  # noqa: F401


def test_config_tables():
    from pricing.config import DIM_MATERIAL, DIM_ESTABLECIMIENTO, FACT_VENTAS, FACT_MARGEN

    assert "dim_materialcomercial" in DIM_MATERIAL
    assert "dim_establecimiento" in DIM_ESTABLECIMIENTO
    assert "weekly_ventas" in FACT_VENTAS
    assert "weekly_margen" in FACT_MARGEN


def test_waterfall_codes():
    from pricing.config import WATERFALL_CODES

    assert WATERFALL_CODES["050"] == "tarifa"
    assert WATERFALL_CODES["210"] == "descuento"
    assert WATERFALL_CODES["890"] == "coste_producto"


def test_build_features(spark):
    from pricing.features.engineering import build_features

    df = spark.createDataFrame([(1, 10.0), (2, 20.0)], ["id", "price"])
    result = build_features(df)
    assert result.count() == 2

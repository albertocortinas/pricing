def test_import():
    import pricing  # noqa: F401


def test_build_features(spark):
    from pricing.features.engineering import build_features

    df = spark.createDataFrame([(1, 10.0), (2, 20.0)], ["id", "price"])
    result = build_features(df)
    assert result.count() == 2

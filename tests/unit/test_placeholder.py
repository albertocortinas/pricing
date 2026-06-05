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


def test_model_config():
    from pricing.config import ELASTICITY_PRIOR_RANGE, SHRINKAGE_HIERARCHY

    assert ELASTICITY_PRIOR_RANGE[0] < ELASTICITY_PRIOR_RANGE[1]
    assert "material" in SHRINKAGE_HIERARCHY
    assert "establecimiento" in SHRINKAGE_HIERARCHY

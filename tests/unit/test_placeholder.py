"""Smoke tests for config constants."""


def test_config_tables():
    DIM_MATERIAL = "damm_gold_des.dm.dim_materialcomercial"
    DIM_ESTABLECIMIENTO = "damm_gold_des.dm.dim_establecimiento"
    FACT_VENTAS = "damm_gold_des.venta_litros_margen.weekly_ventas_material_distribuidor_disagg"
    FACT_MARGEN = "damm_gold_des.venta_litros_margen.weekly_margen_material_distribuidor_disagg"

    assert "dim_materialcomercial" in DIM_MATERIAL
    assert "dim_establecimiento" in DIM_ESTABLECIMIENTO
    assert "weekly_ventas" in FACT_VENTAS
    assert "weekly_margen" in FACT_MARGEN


def test_waterfall_codes():
    WATERFALL_CODES = {
        "050": "tarifa",
        "100": "obsequios",
        "210": "descuento",
        "300": "promo",
        "420": "amortizacion",
        "740": "rappel",
        "858": "impuestos_especiales",
        "859": "ecotasa_punto_verde",
        "861": "coste_logistico",
        "890": "coste_producto",
        "954": "mano_obra_ib",
        "956": "amortizacion_ib",
        "900": "tarifa_distribuidor",
        "901": "impuestos_distribuidor",
        "902": "pa_distribuidor",
        "920": "colaboracion",
    }

    assert WATERFALL_CODES["050"] == "tarifa"
    assert WATERFALL_CODES["210"] == "descuento"
    assert WATERFALL_CODES["890"] == "coste_producto"


def test_model_config():
    ELASTICITY_PRIOR_RANGE = (-2.5, -0.2)
    SHRINKAGE_HIERARCHY = {
        "material": ["Lineadeproducto", "Marca"],
        "establecimiento": ["Categoria", "Provincia"],
    }

    assert ELASTICITY_PRIOR_RANGE[0] < ELASTICITY_PRIOR_RANGE[1]
    assert "material" in SHRINKAGE_HIERARCHY
    assert "establecimiento" in SHRINKAGE_HIERARCHY

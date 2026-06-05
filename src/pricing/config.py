# ---------------------------------------------------------------------------
# Unity Catalog table references
# ---------------------------------------------------------------------------
DIM_MATERIAL = "damm_gold_des.dm.dim_materialcomercial"
DIM_ESTABLECIMIENTO = "damm_gold_des.dm.dim_establecimiento"
FACT_VENTAS = "damm_gold_des.venta_litros_margen.weekly_ventas_material_distribuidor_disagg"
FACT_MARGEN = "damm_gold_des.venta_litros_margen.weekly_margen_material_distribuidor_disagg"

# ---------------------------------------------------------------------------
# Pricing waterfall codes
# ---------------------------------------------------------------------------
WATERFALL_CODES = {
    # Revenue / discounts (from FACT_VENTAS)
    "050": "tarifa",
    "100": "obsequios",
    "210": "descuento",
    "300": "promo",
    "420": "amortizacion",
    "740": "rappel",
    # Costs (from FACT_MARGEN)
    "858": "impuestos_especiales",
    "859": "ecotasa_punto_verde",
    "861": "coste_logistico",
    "890": "coste_producto",
    "954": "mano_obra_ib",
    "956": "amortizacion_ib",
    # Distributor (from FACT_MARGEN)
    "900": "tarifa_distribuidor",
    "901": "impuestos_distribuidor",
    "902": "pa_distribuidor",
    "920": "colaboracion",
}

# Codes sourced from each fact table
VENTAS_CODES = {"050", "100", "210", "300", "420", "740", "100_agua"}
MARGEN_CODES = set(WATERFALL_CODES.keys()) - VENTAS_CODES | {
    "120_agua", "140_agua", "160_agua", "170_agua", "180_agua", "190_agua",
}

# ---------------------------------------------------------------------------
# Reference fields — dynamic lookup with known-value validation
# ---------------------------------------------------------------------------
REFERENCE_FIELDS = {
    DIM_ESTABLECIMIENTO: [
        ("Nacionalidad", "NacionalidadDesc"),
        ("Categoria", "CategoriaDesc"),
        ("TipodeCuenta", "TipodeCuentaDesc"),
        ("DetalledeCuenta", "DetalledeCuentaDesc"),
        ("Temporalidad", "TemporalidadDesc"),
        ("StatusFase", "StatusFaseDesc"),
        ("Idioma", "IdiomaDesc"),
    ],
    DIM_MATERIAL: [
        ("Lineadenegocio", "LineadenegocioDesc"),
        ("Lineadeproducto", "LineadeproductoDesc"),
        ("Marca", "MarcaDesc"),
        ("AgrupadorMarcaReportingGestion", "AgrupadorMarcaReportingGestionDesc2"),
        ("CBR", "CBRDesc"),
    ],
}

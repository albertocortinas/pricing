# Reference: Damm pricing schema, waterfall codes & model config

Source of truth for the `damm-pricing-databricks` skill. Mirror the codebase
constants — if these drift from the actual config module, the code wins; update
this file to match.

## Contents
1. Tables
2. Waterfall code dictionary
3. Code → fact-table sourcing
4. Agrupaciones del waterfall (tarifa → precio en factura → venta neta → margen)
5. Reference fields (dimension lookups)
6. Model configuration
7. Databricks MCP endpoints

---

## 1. Tables

```python
DIM_MATERIAL        = "damm_gold_des.dm.dim_materialcomercial"
DIM_ESTABLECIMIENTO = "damm_gold_des.dm.dim_establecimiento"
FACT_VENTAS         = "damm_gold_des.venta_litros_margen.weekly_ventas_material_distribuidor_disagg"
FACT_MARGEN         = "damm_gold_des.venta_litros_margen.weekly_margen_material_distribuidor_disagg"
```

Grain: both facts are **weekly**, disaggregated to material × distribuidor.

---

## 2. Waterfall code dictionary

| Code | Name | Bucket |
|------|------|--------|
| `050` | tarifa | tarifa (base) |
| `100` | obsequios | on-invoice (tarifa → precio en factura) |
| `210` | descuento | on-invoice (tarifa → precio en factura) |
| `300` | promo | on-invoice (tarifa → precio en factura) |
| `420` | amortizacion | off-invoice (precio en factura → venta neta) |
| `740` | rappel | off-invoice (precio en factura → venta neta) |
| `858` | impuestos_especiales | coste (venta neta → margen) |
| `859` | ecotasa_punto_verde | coste (venta neta → margen) |
| `861` | coste_logistico | coste (venta neta → margen) |
| `890` | coste_producto | coste (venta neta → margen) |
| `954` | mano_obra_ib | coste (venta neta → margen) |
| `956` | amortizacion_ib | coste (venta neta → margen) |
| `900` | tarifa_distribuidor | distribuidor |
| `901` | impuestos_distribuidor | distribuidor |
| `902` | pa_distribuidor | distribuidor |
| `920` | colaboracion | distribuidor |

---

## 3. Code → fact-table sourcing

```python
# From FACT_VENTAS
VENTAS_CODES = {"050", "100", "210", "300", "420", "740", "100_agua"}

# From FACT_MARGEN  (all dictionary codes not in ventas, plus water-cost variants)
MARGEN_CODES = set(WATERFALL_CODES.keys()) - VENTAS_CODES | {
    "120_agua", "140_agua", "160_agua", "170_agua", "180_agua", "190_agua",
}
```

The `_agua` codes are water-line specific and are easy to miss — they are not in
the main dictionary. Check this list before deciding a code is unknown.

---

## 4. Agrupaciones del waterfall (tarifa → precio en factura → venta neta → margen)

```python
ON_INVOICE_CODES  = {"100", "210", "300"}                       # tarifa → precio en factura
OFF_INVOICE_CODES = {"420", "740"}                              # precio en factura → venta neta
COST_CODES        = {"858", "859", "861", "890", "954", "956"}  # venta neta → margen
DISTRIBUTOR_CODES = {"900", "901", "902", "920"}                # distribuidor
```

Waterfall direction (confirm the exact arithmetic/signs against the pipeline
before relying on it):

```
tarifa (050)
  − on-invoice (100, 210, 300)
  = precio en factura
  − off-invoice (420, 740)
  = venta neta
  − costes (858, 859, 861, 890, 954, 956)
  = margen
```

Always classify by these sets, never by inline literals — adding a new code then
means editing one set, not hunting through transforms.

---

## 5. Reference fields (dimension lookups)

Dynamic lookup with known-value validation — code/description column pairs:

```python
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
```

Each tuple is `(code_column, description_column)`. Join on the code, surface the
description in outputs.

---

## 6. Model configuration

```python
# Plausible elasticity band from literature (Tellis 1988, Bijmolt et al. 2005)
ELASTICITY_PRIOR_RANGE = (-2.5, -0.2)

# December 1 tariff step — quasi-experiment anchor for identification
TARIFF_STEP_DATE = "12-01"

# Hierarchical shrinkage grouping (L0 -> L3 fallback)
SHRINKAGE_HIERARCHY = {
    "material":        ["CBR", "Marca"],
    "establecimiento": ["Categoria", "Provincia"],
}

# Temporal granularity per price component
TEMPORAL_GRANULARITY = {
    "base_price": "monthly",
    "promotions": "weekly",
}
```

Notes:
- Elasticities outside `ELASTICITY_PRIOR_RANGE` are a signal to investigate
  (collinearity, weak identification, bad code mapping), not to clip.
- `TARIFF_STEP_DATE` is the staggered-rollout event used for empirical
  re-estimation — the diagnostic regression is a check, the tariff step is the
  identification source.
- Preserve the monthly-base / weekly-promo split when building features.

---

## 7. Databricks MCP endpoints (workspace adb-988092414607846.6)

Managed MCP server URL patterns for this workspace:

```
DBSQL          https://adb-988092414607846.6.azuredatabricks.net/api/2.0/mcp/sql
Genie          https://adb-988092414607846.6.azuredatabricks.net/api/2.0/mcp/genie/{genie_space_id}
Vector Search  https://adb-988092414607846.6.azuredatabricks.net/api/2.0/mcp/vector-search/{catalog}/{schema}
UC Functions   https://adb-988092414607846.6.azuredatabricks.net/api/2.0/mcp/functions/{catalog}/{schema}
```

Confirm live endpoints in the workspace UI: **Agents > MCP Servers**. The
Managed MCP Servers feature is in Beta and must be enabled under workspace
previews. Auth is OAuth on first call; Unity Catalog permissions are enforced.

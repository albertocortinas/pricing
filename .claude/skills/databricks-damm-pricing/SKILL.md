---
name: damm-pricing-databricks
description: >-
  Conventions and domain knowledge for the Damm HORECA pricing/margin codebase
  on Databricks (PySpark + Unity Catalog). Use this skill whenever working on
  anything touching the damm_bronze_des / damm_silver_des / damm_gold_des
  catalogs, the pricing waterfall, pocket price or pocket margin computation,
  demand elasticity modelling, the weekly ventas/margen disagg fact tables, or
  the dim_materialcomercial / dim_establecimiento dimensions — even when the
  request just mentions "the pricing model", "the margin pipeline", "elasticity",
  "waterfall codes", or HORECA pricing without naming Databricks explicitly.
  Read references/schema.md before writing or modifying any query, transform,
  or model that references these tables or codes.
---

# Damm HORECA pricing & margin (Databricks)

This skill encodes the conventions of the Damm pricing/margin codebase so that
queries, PySpark transforms, and modelling work stay consistent with how the
data is actually laid out. The full table map, waterfall code dictionary,
reference fields, and model configuration live in `references/schema.md` — read
it before touching anything that references these tables or codes; the values
below are summaries, not the source of truth.

## Catalog layering (medallion)

Three Unity Catalog catalogs, bronze → silver → gold:

- `damm_bronze_des` — raw / ingested.
- `damm_silver_des` — cleaned / conformed.
- `damm_gold_des` — curated marts; **this is what analysis and modelling read
  from.** Default to gold unless you are explicitly debugging upstream.

Never hardcode `hive_metastore`. Always use the three-level
`<catalog>.<schema>.<table>` namespace. The `_des` suffix is the dev
environment — be deliberate before pointing anything at a non-`_des` catalog.

## The four core gold tables

| Role | Table |
|------|-------|
| Material dimension | `damm_gold_des.dm.dim_materialcomercial` |
| Establecimiento dimension | `damm_gold_des.dm.dim_establecimiento` |
| Sales fact (weekly) | `damm_gold_des.venta_litros_margen.weekly_ventas_material_distribuidor_disagg` |
| Margin fact (weekly) | `damm_gold_des.venta_litros_margen.weekly_margen_material_distribuidor_disagg` |

Both fact tables are **weekly** grain, disaggregated to material × distribuidor.
Join facts to dimensions on the material and establecimiento keys.

## The pricing waterfall

Revenue/discount components come from the **ventas** fact; cost and distributor
components come from the **margen** fact. Each component is a numeric code. The
codes are grouped for pocket-price/pocket-margin computation as follows:

- **List / base**: `050` (tarifa) — the starting list price.
- **On-invoice** (`100`, `210`, `300`): obsequios, descuento, promo — deducted
  from list to reach the invoice price.
- **Off-invoice** (`420`, `740`): amortización, rappel — deducted from invoice
  to reach the **pocket price**.
- **Costs** (`858`, `859`, `861`, `890`, `954`, `956`): impuestos especiales,
  ecotasa/punto verde, logístico, producto, mano de obra IB, amortización IB —
  deducted from pocket price to reach **pocket margin**.
- **Distributor** (`900`, `901`, `902`, `920`): tarifa, impuestos, PA,
  colaboración — distributor-side components.

When computing pocket price or pocket margin, classify codes by these groups
rather than listing literals inline — the canonical sets live in
`references/schema.md` and in the codebase constants. If a code appears that is
not in the dictionary (e.g. an `_agua` variant), check `references/schema.md`
for the water-specific codes before assuming it belongs to a group.

## Querying live data (Databricks MCP)

If the Databricks managed MCP servers are connected (see `references/schema.md`
for the workspace endpoints), prefer the DBSQL server for ad-hoc reads against
gold tables, and a Genie space if one is curated for pricing. Unity Catalog
permissions are enforced through the MCP layer, so a query only sees tables the
user can already access. Before running an exploratory query, `LIMIT` it; never
`collect()` an unbounded fact-table read.

## PySpark conventions

- Use the DataFrame API for transforms, not raw SQL strings, so logic stays
  testable and column lineage is clear. Spark SQL is fine for quick reads.
- Inspect with `.limit(n)` then `.show()` / `.toPandas()` — never `.collect()`
  on a full fact table (they are weekly × material × distribuidor and large).
- When pivoting the waterfall, drive the pivot off the code groups above, not a
  hand-written list, so new codes are handled by updating one dictionary.

## Modelling conventions (demand elasticity)

These mirror the codebase constants — see `references/schema.md` for exact values:

- Elasticities are expected within a literature-plausible band; values outside
  the prior range are a red flag to investigate, not to clip silently.
- The December 1 tariff step (`12-01`) is the quasi-experiment anchor for
  identification — treat it as the staggered-rollout event, not a nuisance.
- Hierarchical shrinkage groups material by CBR/Marca and establecimiento by
  Categoría/Provincia (the L0→L3 fallback). Respect this hierarchy when adding
  new shrinkage levels.
- Base price is modelled monthly; promotions weekly. Keep that temporal split
  intact when constructing features.

## When in doubt

If a code, table, or grouping is ambiguous, read `references/schema.md` first;
if it is still ambiguous (e.g. an undocumented code, or whether a non-`_des`
catalog is intended), ask rather than guessing — pricing arithmetic is
unforgiving and a misclassified code silently corrupts every downstream margin.

# Databricks notebook source
# MAGIC %md
# MAGIC # Consolidación ventas + margen → valores unitarios (€/litro)
# MAGIC
# MAGIC Este notebook:
# MAGIC 1. Lee las tablas semanales de **ventas** y **margen** (gold).
# MAGIC 2. Consolida ambas en un único DataFrame con todos los códigos waterfall.
# MAGIC 3. Calcula los niveles del waterfall: **tarifa → precio en factura → venta neta → margen**.
# MAGIC 4. Obtiene los valores unitarios por litro para cada componente.

# COMMAND ----------

# MAGIC %md
# MAGIC ## 0. Configuración

# COMMAND ----------

from pyspark.sql import functions as F

# -- Tablas gold ---------------------------------------------------------------
FACT_VENTAS = "damm_gold_des.venta_litros_margen.weekly_ventas_material_distribuidor_disagg"
FACT_MARGEN = "damm_gold_des.venta_litros_margen.weekly_margen_material_distribuidor_disagg"

# -- Claves de join ------------------------------------------------------------
JOIN_KEYS = ["Establecimiento", "Detallista", "Material", "Week-Month-Year", "Distribuidor"]

# -- Códigos waterfall por origen ----------------------------------------------
# Ventas: códigos que solo se leen de la tabla de ventas
VENTAS_ONLY_CODES = ["050", "100", "210", "300", "420", "740", "100_agua"]

# Margen: códigos exclusivos de la tabla de margen
MARGEN_ONLY_CODES = [
    "858", "859", "861", "890", "954", "956",   # costes
    "900", "901", "902", "920",                   # distribuidor
    "120_agua", "140_agua", "160_agua",            # agua (margen)
    "170_agua", "180_agua", "190_agua",
]

# -- Agrupaciones para el waterfall --------------------------------------------
ON_INVOICE_CODES  = ["100", "210", "300"]
OFF_INVOICE_CODES = ["420", "740"]
COST_CODES        = ["858", "859", "861", "890", "954", "956"]
DISTRIBUTOR_CODES = ["900", "901", "902", "920"]

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Lectura de tablas

# COMMAND ----------

df_ventas_raw = spark.read.table(FACT_VENTAS)
df_margen_raw = spark.read.table(FACT_MARGEN)

print(f"Ventas: {df_ventas_raw.count():,} filas")
print(f"Margen: {df_margen_raw.count():,} filas")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Selección de columnas por origen
# MAGIC
# MAGIC Cada código se toma de su tabla fuente (según `references/schema.md`).
# MAGIC Los códigos 100–740 aparecen en ambas tablas pero se usan los de **ventas**.

# COMMAND ----------

# De ventas: claves + litros + códigos ventas + VentaNeta
ventas_cols = JOIN_KEYS + ["Litros", "CantidadUMB", "VentaNeta"] + VENTAS_ONLY_CODES
df_ventas = df_ventas_raw.select(*[F.col(f"`{c}`") for c in ventas_cols])

# De margen: claves + códigos exclusivos margen + Margen
margen_cols = JOIN_KEYS + ["Margen"] + MARGEN_ONLY_CODES
df_margen = df_margen_raw.select(*[F.col(f"`{c}`") for c in margen_cols])

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Join → DataFrame consolidado

# COMMAND ----------

join_expr = [F.col(f"v.`{k}`") == F.col(f"m.`{k}`") for k in JOIN_KEYS]

df_consolidado = (
    df_ventas.alias("v")
    .join(df_margen.alias("m"), on=join_expr, how="inner")
    .select(
        # Claves (de ventas)
        *[F.col(f"v.`{k}`").alias(k) for k in JOIN_KEYS],
        # Volumen
        F.col("v.Litros"),
        F.col("v.CantidadUMB"),
        # Totales pre-calculados
        F.col("v.VentaNeta"),
        F.col("m.Margen"),
        # Códigos de ventas
        *[F.col(f"v.`{c}`").alias(c) for c in VENTAS_ONLY_CODES],
        # Códigos de margen
        *[F.col(f"m.`{c}`").alias(c) for c in MARGEN_ONLY_CODES],
    )
)

print(f"Consolidado: {df_consolidado.count():,} filas, {len(df_consolidado.columns)} columnas")
df_consolidado.printSchema()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Niveles del waterfall
# MAGIC
# MAGIC ```
# MAGIC tarifa (050)
# MAGIC   − on-invoice (100, 210, 300)
# MAGIC   = precio en factura
# MAGIC   − off-invoice (420, 740)
# MAGIC   = venta neta
# MAGIC   − costes (858, 859, 861, 890, 954, 956)
# MAGIC   = margen
# MAGIC ```

# COMMAND ----------

def _sum_codes(codes):
    """Suma de una lista de códigos waterfall, tratando nulls como 0."""
    return sum(F.coalesce(F.col(f"`{c}`"), F.lit(0)) for c in codes)


df_waterfall = df_consolidado.withColumns({
    # Nivel 1: tarifa
    "tarifa": F.col("`050`"),

    # Nivel 2: precio en factura = tarifa - on_invoice
    "precio_en_factura": F.col("`050`") - _sum_codes(ON_INVOICE_CODES),

    # Nivel 3: venta neta = precio en factura - off_invoice
    "venta_neta": F.col("`050`") - _sum_codes(ON_INVOICE_CODES) - _sum_codes(OFF_INVOICE_CODES),

    # Nivel 4: margen = venta neta - costes
    "margen_calc": (
        F.col("`050`")
        - _sum_codes(ON_INVOICE_CODES)
        - _sum_codes(OFF_INVOICE_CODES)
        - _sum_codes(COST_CODES)
    ),

    # Subtotales por bloque (para análisis)
    "total_on_invoice":  _sum_codes(ON_INVOICE_CODES),
    "total_off_invoice": _sum_codes(OFF_INVOICE_CODES),
    "total_costes":      _sum_codes(COST_CODES),
    "total_distribuidor": _sum_codes(DISTRIBUTOR_CODES),
})

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Valores unitarios (€ / litro)
# MAGIC
# MAGIC Dividimos cada componente entre `Litros` para obtener valores unitarios.

# COMMAND ----------

# Columnas a convertir a €/litro
UNIT_COLS = (
    ["tarifa", "precio_en_factura", "venta_neta", "margen_calc",
     "total_on_invoice", "total_off_invoice", "total_costes", "total_distribuidor"]
    + VENTAS_ONLY_CODES
    + MARGEN_ONLY_CODES
)

unit_exprs = {
    f"{c}_por_litro": F.when(F.col("Litros") != 0, F.col(f"`{c}`") / F.col("Litros"))
    for c in UNIT_COLS
}

df_unitario = df_waterfall.withColumns(unit_exprs)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Vista rápida

# COMMAND ----------

display(
    df_unitario
    .select(
        "Material", "`Week-Month-Year`", "Distribuidor",
        "Litros",
        "tarifa_por_litro",
        "precio_en_factura_por_litro",
        "venta_neta_por_litro",
        "margen_calc_por_litro",
    )
    .limit(200)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Registro como tabla temporal (opcional)
# MAGIC
# MAGIC Descomentar para persistir o registrar como vista temporal.

# COMMAND ----------

# df_unitario.createOrReplaceTempView("waterfall_unitario")
# df_unitario.write.mode("overwrite").saveAsTable("damm_gold_des.venta_litros_margen.waterfall_unitario")

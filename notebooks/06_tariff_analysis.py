# Databricks notebook source

# COMMAND ----------

# MAGIC %run ./00_config

# COMMAND ----------

# MAGIC %run ./01_functions

# COMMAND ----------

# MAGIC %md
# MAGIC # Tariff (050) Change Analysis by Establecimiento / Material
# MAGIC
# MAGIC Analyzes how the base tariff evolves over time at the store × product level:
# MAGIC 1. **Tariff timeline** — when and how much does the tariff change?
# MAGIC 2. **Change detection** — flag week-over-week tariff steps per cell
# MAGIC 3. **December step pattern** — validate the annual tariff revision around Dec-1
# MAGIC 4. **Distribution of changes** — magnitude, direction, and frequency
# MAGIC 5. **Coverage** — how many Establecimiento × Material cells have tariff variation?

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Load data & build waterfall

# COMMAND ----------

ventas = load_fact_ventas(spark)
margen = load_fact_margen(spark)
waterfall = build_pocket_price_waterfall(ventas, margen)

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Tariff summary per Establecimiento × Material

# COMMAND ----------

from pyspark.sql import Window

tariff_summary = (
    waterfall
    .groupBy("Establecimiento", "Material")
    .agg(
        F.count("tarifa").alias("n_weeks"),
        F.min("tarifa").alias("tarifa_min"),
        F.max("tarifa").alias("tarifa_max"),
        F.mean("tarifa").alias("tarifa_mean"),
        F.stddev("tarifa").alias("tarifa_std"),
        F.countDistinct("tarifa").alias("n_distinct_tarifa"),
        F.min("`Week-Month-Year`").alias("first_week"),
        F.max("`Week-Month-Year`").alias("last_week"),
    )
    .withColumn(
        "tarifa_range_pct",
        F.when(
            F.col("tarifa_mean") != 0,
            (F.col("tarifa_max") - F.col("tarifa_min")) / F.abs(F.col("tarifa_mean")) * 100,
        ),
    )
    .orderBy(F.col("tarifa_range_pct").desc())
)

tariff_summary.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Cells with vs. without tariff variation

# COMMAND ----------

tariff_summary.groupBy(
    (F.col("n_distinct_tarifa") > 1).alias("has_tariff_change")
).agg(
    F.count("*").alias("n_cells"),
    F.mean("n_weeks").alias("avg_weeks"),
    F.mean("tarifa_mean").alias("avg_tarifa"),
).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Week-over-week tariff change detection

# COMMAND ----------

w = Window.partitionBy("Establecimiento", "Material").orderBy("`Week-Month-Year`")

tariff_changes = (
    waterfall
    .select("Establecimiento", "Material", "`Week-Month-Year`", "tarifa", "Litros")
    .withColumn("tarifa_prev", F.lag("tarifa", 1).over(w))
    .withColumn("tarifa_change", F.col("tarifa") - F.col("tarifa_prev"))
    .withColumn(
        "tarifa_change_pct",
        F.when(
            (F.col("tarifa_prev").isNotNull()) & (F.col("tarifa_prev") != 0),
            F.col("tarifa_change") / F.abs(F.col("tarifa_prev")) * 100,
        ),
    )
    .withColumn("is_change", (F.col("tarifa_change") != 0).cast("int"))
)

tariff_changes.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Only rows where tariff actually changed

# COMMAND ----------

actual_changes = tariff_changes.filter(
    (F.col("tarifa_change").isNotNull()) & (F.col("tarifa_change") != 0)
)

actual_changes.orderBy("`Week-Month-Year`", "Material", "Establecimiento").display()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Change frequency by Material

# COMMAND ----------

actual_changes.groupBy("Material").agg(
    F.count("*").alias("n_changes"),
    F.countDistinct("Establecimiento").alias("n_establecimientos"),
    F.mean("tarifa_change_pct").alias("avg_change_pct"),
    F.min("tarifa_change_pct").alias("min_change_pct"),
    F.max("tarifa_change_pct").alias("max_change_pct"),
    F.countDistinct("`Week-Month-Year`").alias("n_distinct_weeks_with_change"),
).orderBy(F.col("n_changes").desc()).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Change frequency by Establecimiento

# COMMAND ----------

actual_changes.groupBy("Establecimiento").agg(
    F.count("*").alias("n_changes"),
    F.countDistinct("Material").alias("n_materials"),
    F.mean("tarifa_change_pct").alias("avg_change_pct"),
    F.min("tarifa_change_pct").alias("min_change_pct"),
    F.max("tarifa_change_pct").alias("max_change_pct"),
).orderBy(F.col("n_changes").desc()).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. December tariff step analysis
# MAGIC
# MAGIC The model assumes tariff revisions cluster around December 1 (`TARIFF_STEP_DATE`).
# MAGIC Validate this by looking at the monthly distribution of tariff changes.

# COMMAND ----------

monthly_changes = (
    actual_changes
    .withColumn("change_month", F.month("`Week-Month-Year`"))
    .withColumn("change_year", F.year("`Week-Month-Year`"))
    .groupBy("change_year", "change_month")
    .agg(
        F.count("*").alias("n_changes"),
        F.countDistinct("Establecimiento").alias("n_establecimientos"),
        F.countDistinct("Material").alias("n_materials"),
        F.mean("tarifa_change_pct").alias("avg_change_pct"),
        F.mean(F.abs("tarifa_change_pct")).alias("avg_abs_change_pct"),
    )
    .orderBy("change_year", "change_month")
)

monthly_changes.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Tariff changes by month (aggregated across years)

# COMMAND ----------

(
    actual_changes
    .withColumn("change_month", F.month("`Week-Month-Year`"))
    .groupBy("change_month")
    .agg(
        F.count("*").alias("n_changes"),
        F.mean("tarifa_change_pct").alias("avg_change_pct"),
        F.mean(F.abs("tarifa_change_pct")).alias("avg_abs_change_pct"),
    )
    .orderBy("change_month")
).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Pre vs. post December comparison
# MAGIC
# MAGIC Compare tariff levels in the weeks immediately before and after December 1.

# COMMAND ----------

dec_window = (
    waterfall
    .select("Establecimiento", "Material", "`Week-Month-Year`", "tarifa", "Litros")
    .withColumn("month", F.month("`Week-Month-Year`"))
    .withColumn("year", F.year("`Week-Month-Year`"))
    .withColumn(
        "period",
        F.when(F.col("month").between(10, 11), "pre_dec")
         .when(F.col("month") == 12, "dec")
         .when(F.col("month").between(1, 2), "post_dec"),
    )
    .filter(F.col("period").isNotNull())
)

dec_comparison = (
    dec_window
    .groupBy("Establecimiento", "Material", "year", "period")
    .agg(
        F.mean("tarifa").alias("avg_tarifa"),
        F.sum("Litros").alias("total_litros"),
    )
    .groupBy("year", "period")
    .agg(
        F.mean("avg_tarifa").alias("grand_avg_tarifa"),
        F.sum("total_litros").alias("grand_total_litros"),
        F.count("*").alias("n_cells"),
    )
    .orderBy("year", "period")
)

dec_comparison.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Distribution of tariff change magnitudes

# COMMAND ----------

actual_changes.select("tarifa_change_pct").describe().display()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Change direction breakdown

# COMMAND ----------

actual_changes.groupBy(
    F.when(F.col("tarifa_change_pct") > 0, "increase")
     .when(F.col("tarifa_change_pct") < 0, "decrease")
     .otherwise("zero")
     .alias("direction")
).agg(
    F.count("*").alias("n_changes"),
    F.mean("tarifa_change_pct").alias("avg_change_pct"),
    F.percentile_approx("tarifa_change_pct", 0.5).alias("median_change_pct"),
).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Percentile distribution of absolute tariff changes

# COMMAND ----------

actual_changes.select(
    F.abs("tarifa_change_pct").alias("abs_change_pct")
).agg(
    F.percentile_approx("abs_change_pct", 0.25).alias("p25"),
    F.percentile_approx("abs_change_pct", 0.50).alias("p50"),
    F.percentile_approx("abs_change_pct", 0.75).alias("p75"),
    F.percentile_approx("abs_change_pct", 0.90).alias("p90"),
    F.percentile_approx("abs_change_pct", 0.95).alias("p95"),
    F.percentile_approx("abs_change_pct", 0.99).alias("p99"),
).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Tariff evolution over time (top materials)

# COMMAND ----------

# Pick the top 10 materials by number of tariff changes
top_materials = (
    actual_changes
    .groupBy("Material")
    .count()
    .orderBy(F.col("count").desc())
    .limit(10)
    .select("Material")
)

tariff_timeline = (
    waterfall
    .join(top_materials, on="Material", how="inner")
    .groupBy("Material", "`Week-Month-Year`")
    .agg(
        F.mean("tarifa").alias("avg_tarifa"),
        F.sum("Litros").alias("total_litros"),
        F.countDistinct("Establecimiento").alias("n_establecimientos"),
    )
    .orderBy("Material", "`Week-Month-Year`")
)

tariff_timeline.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Volume response around tariff changes
# MAGIC
# MAGIC For each tariff change event, look at volume in the 4 weeks before and after.

# COMMAND ----------

w_vol = Window.partitionBy("Establecimiento", "Material").orderBy("`Week-Month-Year`")

volume_around_changes = (
    tariff_changes
    .filter((F.col("tarifa_change").isNotNull()) & (F.col("tarifa_change") != 0))
    .withColumn("litros_prev_4w", F.avg("Litros").over(w_vol.rowsBetween(-4, -1)))
    .withColumn("litros_post_4w", F.avg("Litros").over(w_vol.rowsBetween(1, 4)))
    .withColumn(
        "volume_change_pct",
        F.when(
            (F.col("litros_prev_4w").isNotNull()) & (F.col("litros_prev_4w") != 0),
            (F.col("litros_post_4w") - F.col("litros_prev_4w"))
            / F.abs(F.col("litros_prev_4w"))
            * 100,
        ),
    )
)

volume_around_changes.select(
    "Establecimiento", "Material", "`Week-Month-Year`",
    "tarifa_change_pct", "litros_prev_4w", "litros_post_4w", "volume_change_pct",
).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Average volume response by tariff change direction

# COMMAND ----------

volume_around_changes.groupBy(
    F.when(F.col("tarifa_change_pct") > 0, "increase")
     .otherwise("decrease")
     .alias("direction")
).agg(
    F.count("*").alias("n_events"),
    F.mean("tarifa_change_pct").alias("avg_tariff_change_pct"),
    F.mean("volume_change_pct").alias("avg_volume_change_pct"),
    F.percentile_approx("volume_change_pct", 0.5).alias("median_volume_change_pct"),
).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## 8. Discount & promotion response after tariff changes
# MAGIC
# MAGIC Do on-invoice deductions (descuento, promo, obsequios) adjust after a tariff step?
# MAGIC Compare average levels in the 4 weeks before vs. 4 weeks after each change event.

# COMMAND ----------

w_cell = Window.partitionBy("Establecimiento", "Material").orderBy("`Week-Month-Year`")

# Build full panel with lagged tariff to detect change rows
deductions_panel = (
    waterfall
    .select(
        "Establecimiento", "Material", "`Week-Month-Year`",
        "tarifa", "descuento", "promo", "obsequios",
        "amortizacion", "rappel",
        "venta_neta", "pocket_price", "Litros",
    )
    .withColumn("tarifa_prev", F.lag("tarifa", 1).over(w_cell))
    .withColumn("tarifa_change", F.col("tarifa") - F.col("tarifa_prev"))
    .withColumn("is_change", (F.col("tarifa_change") != 0).cast("int"))
    # Pre/post averages for each deduction component
    .withColumn("descuento_prev_4w", F.avg("descuento").over(w_cell.rowsBetween(-4, -1)))
    .withColumn("descuento_post_4w", F.avg("descuento").over(w_cell.rowsBetween(1, 4)))
    .withColumn("promo_prev_4w", F.avg("promo").over(w_cell.rowsBetween(-4, -1)))
    .withColumn("promo_post_4w", F.avg("promo").over(w_cell.rowsBetween(1, 4)))
    .withColumn("obsequios_prev_4w", F.avg("obsequios").over(w_cell.rowsBetween(-4, -1)))
    .withColumn("obsequios_post_4w", F.avg("obsequios").over(w_cell.rowsBetween(1, 4)))
    .withColumn("rappel_prev_4w", F.avg("rappel").over(w_cell.rowsBetween(-4, -1)))
    .withColumn("rappel_post_4w", F.avg("rappel").over(w_cell.rowsBetween(1, 4)))
    .withColumn("venta_neta_prev_4w", F.avg("venta_neta").over(w_cell.rowsBetween(-4, -1)))
    .withColumn("venta_neta_post_4w", F.avg("venta_neta").over(w_cell.rowsBetween(1, 4)))
    .withColumn("pocket_price_prev_4w", F.avg("pocket_price").over(w_cell.rowsBetween(-4, -1)))
    .withColumn("pocket_price_post_4w", F.avg("pocket_price").over(w_cell.rowsBetween(1, 4)))
)

# Filter to tariff change events only
deductions_at_changes = deductions_panel.filter(
    (F.col("tarifa_change").isNotNull()) & (F.col("tarifa_change") != 0)
)

# COMMAND ----------

# MAGIC %md
# MAGIC ### Per-event detail: tariff change vs. deduction shifts

# COMMAND ----------

deductions_at_changes.select(
    "Establecimiento", "Material", "`Week-Month-Year`",
    "tarifa_change",
    "descuento_prev_4w", "descuento_post_4w",
    "promo_prev_4w", "promo_post_4w",
    "obsequios_prev_4w", "obsequios_post_4w",
    "venta_neta_prev_4w", "venta_neta_post_4w",
    "pocket_price_prev_4w", "pocket_price_post_4w",
).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Aggregate: average deduction shift after tariff increases vs. decreases
# MAGIC
# MAGIC Positive delta means the deduction **increased** (more discount given).

# COMMAND ----------

deduction_response = (
    deductions_at_changes
    .withColumn("direction",
        F.when(F.col("tarifa_change") > 0, "increase").otherwise("decrease"),
    )
    .withColumn("descuento_delta", F.col("descuento_post_4w") - F.col("descuento_prev_4w"))
    .withColumn("promo_delta", F.col("promo_post_4w") - F.col("promo_prev_4w"))
    .withColumn("obsequios_delta", F.col("obsequios_post_4w") - F.col("obsequios_prev_4w"))
    .withColumn("rappel_delta", F.col("rappel_post_4w") - F.col("rappel_prev_4w"))
    .withColumn("venta_neta_delta", F.col("venta_neta_post_4w") - F.col("venta_neta_prev_4w"))
    .withColumn("pocket_price_delta", F.col("pocket_price_post_4w") - F.col("pocket_price_prev_4w"))
)

deduction_response.groupBy("direction").agg(
    F.count("*").alias("n_events"),
    F.mean("tarifa_change").alias("avg_tarifa_change"),
    F.mean("descuento_delta").alias("avg_descuento_delta"),
    F.mean("promo_delta").alias("avg_promo_delta"),
    F.mean("obsequios_delta").alias("avg_obsequios_delta"),
    F.mean("rappel_delta").alias("avg_rappel_delta"),
    F.mean("venta_neta_delta").alias("avg_venta_neta_delta"),
    F.mean("pocket_price_delta").alias("avg_pocket_price_delta"),
).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Pass-through ratio: how much of the tariff change reaches pocket price?
# MAGIC
# MAGIC A ratio of 1.0 means the tariff change passes fully to pocket price (no offsetting deductions).
# MAGIC A ratio < 1.0 means deductions absorb part of the tariff change.

# COMMAND ----------

passthrough = (
    deduction_response
    .filter(F.col("tarifa_change") != 0)
    .withColumn(
        "passthrough_ratio",
        F.col("pocket_price_delta") / F.col("tarifa_change"),
    )
)

passthrough.groupBy("direction").agg(
    F.count("*").alias("n_events"),
    F.mean("passthrough_ratio").alias("avg_passthrough"),
    F.percentile_approx("passthrough_ratio", 0.25).alias("p25_passthrough"),
    F.percentile_approx("passthrough_ratio", 0.50).alias("median_passthrough"),
    F.percentile_approx("passthrough_ratio", 0.75).alias("p75_passthrough"),
).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Pass-through by Material

# COMMAND ----------

passthrough.groupBy("Material").agg(
    F.count("*").alias("n_events"),
    F.mean("tarifa_change").alias("avg_tarifa_change"),
    F.mean("descuento_delta").alias("avg_descuento_delta"),
    F.mean("promo_delta").alias("avg_promo_delta"),
    F.mean("pocket_price_delta").alias("avg_pocket_price_delta"),
    F.mean("passthrough_ratio").alias("avg_passthrough"),
).orderBy(F.col("n_events").desc()).display()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Deduction response over time: monthly evolution around December tariff step
# MAGIC
# MAGIC Track how descuento and promo evolve month-by-month around the annual tariff revision.

# COMMAND ----------

monthly_deductions = (
    waterfall
    .withColumn("month", F.month("`Week-Month-Year`"))
    .withColumn("year", F.year("`Week-Month-Year`"))
    .groupBy("year", "month")
    .agg(
        F.mean("tarifa").alias("avg_tarifa"),
        F.mean("descuento").alias("avg_descuento"),
        F.mean("promo").alias("avg_promo"),
        F.mean("obsequios").alias("avg_obsequios"),
        F.mean("rappel").alias("avg_rappel"),
        F.mean("venta_neta").alias("avg_venta_neta"),
        F.mean("pocket_price").alias("avg_pocket_price"),
        (F.mean("descuento") + F.mean("promo") + F.mean("obsequios")).alias("avg_total_on_invoice"),
    )
    .orderBy("year", "month")
)

monthly_deductions.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ### Deduction as % of tarifa — monthly trend
# MAGIC
# MAGIC Shows whether discount intensity increases after tariff hikes to compensate.

# COMMAND ----------

(
    monthly_deductions
    .withColumn(
        "descuento_pct_tarifa",
        F.when(F.col("avg_tarifa") != 0, F.col("avg_descuento") / F.col("avg_tarifa") * 100),
    )
    .withColumn(
        "promo_pct_tarifa",
        F.when(F.col("avg_tarifa") != 0, F.col("avg_promo") / F.col("avg_tarifa") * 100),
    )
    .withColumn(
        "total_on_invoice_pct_tarifa",
        F.when(F.col("avg_tarifa") != 0, F.col("avg_total_on_invoice") / F.col("avg_tarifa") * 100),
    )
    .select("year", "month", "avg_tarifa",
            "descuento_pct_tarifa", "promo_pct_tarifa", "total_on_invoice_pct_tarifa")
    .orderBy("year", "month")
).display()

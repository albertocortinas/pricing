# Databricks notebook source

# COMMAND ----------

# MAGIC %run ./00_config

# COMMAND ----------

# MAGIC %run ./01_functions

# COMMAND ----------

# MAGIC %md
# MAGIC # Data Exploration & Diagnostics (Phase 1)

# COMMAND ----------

ventas = load_fact_ventas(spark)
margen = load_fact_margen(spark)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Pocket price waterfall

# COMMAND ----------

waterfall = build_pocket_price_waterfall(ventas, margen)
waterfall.display()

# COMMAND ----------

waterfall.describe().display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Price band distribution

# COMMAND ----------

price_bands = summarize_price_band(waterfall, group_cols=["Material"])
price_bands.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Leakage analysis

# COMMAND ----------

leakage = summarize_leakage(waterfall, group_cols=["Material"])
leakage.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Sparse cells & negative volume

# COMMAND ----------

sparse = flag_sparse_cells(waterfall, min_periods=12)
sparse.filter("is_sparse = 1").display()

# COMMAND ----------

neg_vol = flag_negative_volume(waterfall)
neg_vol.filter("has_negative_volume = 1").display()

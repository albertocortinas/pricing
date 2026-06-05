# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Data Exploration & Diagnostics (Phase 1)

# COMMAND ----------

from pricing.data.loader import load_fact_ventas, load_fact_margen, load_dim_material, load_dim_establecimiento
from pricing.features.engineering import build_pocket_price_waterfall
from pricing.diagnostics.waterfall import (
    summarize_price_band,
    summarize_leakage,
    flag_sparse_cells,
    flag_negative_volume,
)

# COMMAND ----------

ventas = load_fact_ventas(spark)
margen = load_fact_margen(spark)
dim_mat = load_dim_material(spark)

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

price_bands = summarize_price_band(waterfall, group_cols=["material"])
price_bands.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Leakage analysis

# COMMAND ----------

leakage = summarize_leakage(waterfall, group_cols=["material"])
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

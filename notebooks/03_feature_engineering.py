# Databricks notebook source

# COMMAND ----------

# MAGIC %run ./00_config

# COMMAND ----------

# MAGIC %run ./01_functions

# COMMAND ----------

# MAGIC %md
# MAGIC # Feature Engineering

# COMMAND ----------

ventas = load_fact_ventas(spark)
margen = load_fact_margen(spark)
dim_mat = load_dim_material(spark)
dim_est = load_dim_establecimiento(spark)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build waterfall

# COMMAND ----------

waterfall = build_pocket_price_waterfall(ventas, margen)
waterfall.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Price ratios

# COMMAND ----------

with_ratios = build_price_ratios(waterfall, method="rolling_median")
with_ratios.select("Establecimiento", "Material", "`Week-Month-Year`", "tarifa", "reference_price", "price_ratio").display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Model features

# COMMAND ----------

features = build_model_features(with_ratios, dim_mat, dim_est)
features.display()

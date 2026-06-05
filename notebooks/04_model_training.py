# Databricks notebook source

# COMMAND ----------

# MAGIC %run ./00_config

# COMMAND ----------

# MAGIC %run ./01_functions

# COMMAND ----------

# MAGIC %md
# MAGIC # Model Training (Phase 2)

# COMMAND ----------

ventas = load_fact_ventas(spark)
margen = load_fact_margen(spark)
dim_mat = load_dim_material(spark)
dim_est = load_dim_establecimiento(spark)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Build features

# COMMAND ----------

waterfall = build_pocket_price_waterfall(ventas, margen)
with_ratios = build_price_ratios(waterfall)
features = build_model_features(with_ratios, dim_mat, dim_est)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Fit model per segment

# COMMAND ----------

posterior_df = fit_model_distributed(
    spark,
    features,
    group_cols=["Marca", "Categoria"],
)
posterior_df.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Extract elasticities

# COMMAND ----------

elasticities = extract_elasticities(posterior_df)
elasticities.display()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Elasticity surface

# COMMAND ----------

# surface = build_elasticity_surface(elasticities, dim_grid_df)
# surface.display()

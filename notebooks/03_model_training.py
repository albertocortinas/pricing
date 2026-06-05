# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Model Training (Phase 2)

# COMMAND ----------

from pricing.data.loader import load_fact_ventas, load_fact_margen, load_dim_material, load_dim_establecimiento
from pricing.features.engineering import build_pocket_price_waterfall, build_price_ratios, build_model_features
from pricing.models.response import fit_model_distributed
from pricing.models.elasticity import extract_elasticities, build_elasticity_surface

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

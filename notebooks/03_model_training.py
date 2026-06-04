# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Model Training

# COMMAND ----------

from pricing.data.loader import load_sales
from pricing.features.engineering import build_features
from pricing.models.optimizer import optimize_prices

# COMMAND ----------

df = load_sales(spark)
features = build_features(df)
results = optimize_prices(features)
results.display()

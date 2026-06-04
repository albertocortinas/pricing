# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Feature Engineering

# COMMAND ----------

from pricing.data.loader import load_sales
from pricing.features.engineering import build_features

# COMMAND ----------

df = load_sales(spark)
features = build_features(df)
features.display()

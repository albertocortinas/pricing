# Databricks notebook source
import sys
sys.path.insert(0, "/Workspace/Users/ta-sys-dmm-acm-cloud@sadamm.onmicrosoft.com/pricing/src")


# COMMAND ----------

# MAGIC %md
# MAGIC # Feature Engineering

# COMMAND ----------

from pricing.data.loader import load_fact_ventas
from pricing.features.engineering import build_features

# COMMAND ----------

df = load_fact_ventas(spark)
features = build_features(df)
features.display()

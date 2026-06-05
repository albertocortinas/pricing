# Databricks notebook source
# MAGIC %md
# MAGIC # Data Exploration

# COMMAND ----------

# DBTITLE 1,Cell 3
import sys
sys.path.insert(0, "/Workspace/Users/ta-sys-dmm-acm-cloud@sadamm.onmicrosoft.com/pricing/src")
from pricing.data.loader import load_fact_ventas

# COMMAND ----------

df = load_fact_ventas(spark)
df.display()

# COMMAND ----------

df.describe().display()

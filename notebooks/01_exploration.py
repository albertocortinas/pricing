# Databricks notebook source

# COMMAND ----------

# MAGIC %md
# MAGIC # Data Exploration

# COMMAND ----------

from pricing.data.loader import load_sales

# COMMAND ----------

df = load_sales(spark)
df.display()

# COMMAND ----------

df.describe().display()

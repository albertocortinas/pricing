from pyspark.sql import DataFrame, SparkSession

from pricing import config


def load_dim_material(spark: SparkSession) -> DataFrame:
    return spark.read.table(config.DIM_MATERIAL)


def load_dim_establecimiento(spark: SparkSession) -> DataFrame:
    return spark.read.table(config.DIM_ESTABLECIMIENTO)


def load_fact_ventas(spark: SparkSession) -> DataFrame:
    return spark.read.table(config.FACT_VENTAS)


def load_fact_margen(spark: SparkSession) -> DataFrame:
    return spark.read.table(config.FACT_MARGEN)

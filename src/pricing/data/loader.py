from pyspark.sql import DataFrame, SparkSession

from pricing.config import RAW_SALES_TABLE


def load_sales(spark: SparkSession, table: str = RAW_SALES_TABLE) -> DataFrame:
    """Load sales data from Unity Catalog."""
    return spark.read.table(table)

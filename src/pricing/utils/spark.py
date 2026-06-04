from pyspark.sql import SparkSession


def get_spark() -> SparkSession:
    """Return the active SparkSession or create a local one for development."""
    return SparkSession.builder.getOrCreate()

"""Dynamic reference lookups with known-value validation."""

import logging
from typing import Dict, Optional, Set, Tuple

from pyspark.sql import SparkSession

from pricing.config import REFERENCE_FIELDS

logger = logging.getLogger(__name__)

# Cache: {(table, code_col): {known_values}}
_known_values: Dict[Tuple[str, str], Set[str]] = {}


def get_reference_values(
    spark: SparkSession,
    table: str,
    code_col: str,
    desc_col: str,
) -> Dict[str, str]:
    """Return {code: description} from a dimension table."""
    rows = (
        spark.read.table(table)
        .select(code_col, desc_col)
        .distinct()
        .collect()
    )
    return {str(r[code_col]): r[desc_col] for r in rows}


def validate_reference(
    spark: SparkSession,
    table: str,
    code_col: str,
    desc_col: str,
    known: Optional[Set[str]] = None,
) -> Dict[str, str]:
    """Load reference values and warn on unknowns if known set is provided.

    If *known* is None, purely dynamic — no validation.
    If *known* is provided, new values are logged as warnings.
    """
    values = get_reference_values(spark, table, code_col, desc_col)
    current_codes = set(values.keys())

    if known is not None:
        new_codes = current_codes - known
        if new_codes:
            logger.warning(
                "New values in %s.%s not in known set: %s",
                table, code_col, new_codes,
            )

    return values


def load_all_references(
    spark: SparkSession,
    known_values: Optional[Dict[Tuple[str, str], Set[str]]] = None,
) -> Dict[Tuple[str, str], Dict[str, str]]:
    """Load and validate all reference fields defined in config.

    Parameters
    ----------
    known_values : optional dict mapping (table, code_col) to a set of
        expected code values. When provided, unknown codes trigger warnings.
    """
    known_values = known_values or {}
    result = {}
    for table, fields in REFERENCE_FIELDS.items():
        for code_col, desc_col in fields:
            known = known_values.get((table, code_col))
            result[(table, code_col)] = validate_reference(
                spark, table, code_col, desc_col, known=known,
            )
    return result

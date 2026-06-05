"""Pure, Spark-agnostic logic for the Fabric/OneLake pilot notebooks.

The four pilot notebooks are thin entrypoints. All decision logic that can be
expressed without a Spark session lives here so it is unit-testable without a
cluster, in keeping with the pilot's governing principle: contracts are enforced
by tested code that fails loudly, never asserted only in documentation.
"""

from __future__ import annotations

from .metrics import FileMetrics, compute_file_metrics
from .readiness import ReadinessResult, evaluate_directlake_readiness
from .schema_bridge import (
    SPARK_TO_LOGICAL,
    logical_type_for_spark_type,
    spark_schema_to_logical,
)

__all__ = [
    "FileMetrics",
    "compute_file_metrics",
    "ReadinessResult",
    "evaluate_directlake_readiness",
    "SPARK_TO_LOGICAL",
    "logical_type_for_spark_type",
    "spark_schema_to_logical",
]

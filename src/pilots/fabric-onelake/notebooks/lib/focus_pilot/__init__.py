"""Pure, Spark-agnostic logic for the Fabric/OneLake pilot notebooks.

The four pilot notebooks are thin entrypoints. All decision logic that can be
expressed without a Spark session lives here so it is unit-testable without a
cluster, in keeping with the pilot's governing principle: contracts are enforced
by tested code that fails loudly, never asserted only in documentation.
"""

from __future__ import annotations

from .metrics import (
    ActiveFileMismatch,
    FileMetrics,
    compute_file_metrics,
    select_active_file_sizes,
)
from .promotion import (
    PromotionDecision,
    ZorderRecommendation,
    evaluate_directlake_promotion,
    recommend_zorder,
)
from .readiness import (
    GuardrailsNotConfigured,
    LayoutPreconditionResult,
    directlake_guardrails,
    evaluate_directlake_layout_precondition,
)
from .restatement import (
    ImplausibleRestatement,
    charge_month_predicate,
    check_restatement_ratio,
)
from .schema_bridge import (
    SPARK_TO_LOGICAL,
    logical_type_for_spark_type,
    spark_schema_to_logical,
)

__all__ = [
    "ActiveFileMismatch",
    "FileMetrics",
    "compute_file_metrics",
    "select_active_file_sizes",
    "PromotionDecision",
    "ZorderRecommendation",
    "evaluate_directlake_promotion",
    "recommend_zorder",
    "GuardrailsNotConfigured",
    "LayoutPreconditionResult",
    "directlake_guardrails",
    "evaluate_directlake_layout_precondition",
    "ImplausibleRestatement",
    "charge_month_predicate",
    "check_restatement_ratio",
    "SPARK_TO_LOGICAL",
    "logical_type_for_spark_type",
    "spark_schema_to_logical",
]

"""Unit tests for the pure focus_pilot library logic.

Run: python -m pytest src/pilots/fabric-onelake/notebooks/tests/test_focus_pilot.py
or:  python src/pilots/fabric-onelake/notebooks/tests/test_focus_pilot.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

from focus_pilot.metrics import (
    ActiveFileMismatch,
    compute_file_metrics,
    select_active_file_sizes,
)
from focus_pilot.readiness import (
    GuardrailsNotConfigured,
    directlake_guardrails,
    evaluate_directlake_layout_precondition,
)
from focus_pilot.schema_bridge import (
    find_unsupported_directlake_types,
    logical_type_for_spark_type,
    spark_schema_to_logical,
)

_MB = 1024 * 1024


# --- schema_bridge --------------------------------------------------------- #


def test_logical_type_maps_decimal_with_precision() -> None:
    assert logical_type_for_spark_type("decimal(38,18)") == "decimal"


def test_logical_type_maps_basic_types() -> None:
    assert logical_type_for_spark_type("string") == "string"
    assert logical_type_for_spark_type("double") == "double"
    assert logical_type_for_spark_type("timestamp") == "timestamp"
    assert logical_type_for_spark_type("boolean") == "boolean"


def test_logical_type_rejects_unknown() -> None:
    try:
        logical_type_for_spark_type("variant")
    except ValueError:
        return
    raise AssertionError("Expected ValueError for unmapped type")


def test_spark_schema_to_logical() -> None:
    observed = {"BilledCost": "double", "ServiceName": "string", "ChargePeriodStart": "timestamp"}
    assert spark_schema_to_logical(observed) == {
        "BilledCost": "double",
        "ServiceName": "string",
        "ChargePeriodStart": "timestamp",
    }


def test_find_unsupported_directlake_types() -> None:
    observed = {
        "ServiceName": "string",
        "Tags": "map<string,string>",
        "Nested": "struct<a:int>",
        "Arr": "array<string>",
        "BilledCost": "double",
    }
    assert sorted(find_unsupported_directlake_types(observed)) == ["Arr", "Nested", "Tags"]


# --- metrics --------------------------------------------------------------- #


def test_compute_file_metrics_basic() -> None:
    sizes = [128 * _MB, 128 * _MB, 8 * _MB]
    m = compute_file_metrics(sizes, small_file_threshold_mb=16)
    assert m.file_count == 3
    assert m.small_file_fraction == round(1 / 3, 4)
    assert abs(m.avg_file_size_mb - round((264 / 3), 3)) < 0.01


def test_compute_file_metrics_empty() -> None:
    m = compute_file_metrics([], small_file_threshold_mb=16)
    assert m.file_count == 0
    assert m.avg_file_size_mb == 0.0
    assert m.small_file_fraction == 0.0


# --- active-file selection ------------------------------------------------- #


def test_active_files_exclude_superseded_files() -> None:
    # OPTIMIZE leaves the files it replaced on disk until VACUUM; a plain listing
    # sees both generations. Only the Delta log's active set may be measured.
    listed = [
        ("abfss://ws@host/t/part-old-1.parquet", 4 * _MB),
        ("abfss://ws@host/t/part-old-2.parquet", 4 * _MB),
        ("abfss://ws@host/t/part-new-1.parquet", 128 * _MB),
    ]
    active = ["abfss://ws@host/t/part-new-1.parquet"]
    assert select_active_file_sizes(listed, active) == [128 * _MB]


def test_active_files_tolerate_scheme_and_encoding_differences() -> None:
    listed = [("abfss://ws@host/t/x%20y/part-1.parquet", 99)]
    active = ["https://host/t/x y/part-1.parquet"]
    assert select_active_file_sizes(listed, active) == [99]


def test_active_files_empty_table_returns_no_sizes() -> None:
    assert select_active_file_sizes([("a/part-1.parquet", 10)], []) == []


def test_active_files_raise_when_nothing_matches() -> None:
    # A total mismatch means normalization failed, not that the table is empty.
    # Reporting zero files would hand the SLA check a fabricated result.
    try:
        select_active_file_sizes([("a/part-1.parquet", 10)], ["b/part-2.parquet"])
    except ActiveFileMismatch:
        return
    raise AssertionError("Expected ActiveFileMismatch")


# --- layout precondition --------------------------------------------------- #


def _ready_kwargs(**overrides):
    base = dict(
        compaction_healthy=True,
        unsupported_type_columns=[],
        row_count=1000,
        max_rows=1_500_000_000,
        file_count=10,
        max_files=10_000,
        avg_file_size_mb=128.0,
        min_avg_file_size_mb=64.0,
    )
    base.update(overrides)
    return base


def test_precondition_passes_when_all_conditions_met() -> None:
    result = evaluate_directlake_layout_precondition(**_ready_kwargs())
    assert result.meets_precondition is True
    assert result.reasons == []
    assert all(result.checks.values())


def test_precondition_blocked_on_unhealthy_compaction() -> None:
    result = evaluate_directlake_layout_precondition(**_ready_kwargs(compaction_healthy=False))
    assert result.meets_precondition is False
    assert result.checks["compaction_healthy"] is False


def test_precondition_blocked_on_complex_types() -> None:
    result = evaluate_directlake_layout_precondition(**_ready_kwargs(unsupported_type_columns=["Tags"]))
    assert result.meets_precondition is False
    assert result.checks["no_unsupported_types"] is False


def test_precondition_blocked_on_volume() -> None:
    result = evaluate_directlake_layout_precondition(**_ready_kwargs(row_count=2_000_000_000))
    assert result.meets_precondition is False
    assert result.checks["within_volume_guardrails"] is False


def test_precondition_blocked_on_small_files() -> None:
    result = evaluate_directlake_layout_precondition(**_ready_kwargs(avg_file_size_mb=8.0))
    assert result.meets_precondition is False
    assert result.checks["avg_file_size_ok"] is False


def test_guardrails_reads_contract() -> None:
    contract = {"directLake": {"maxRows": 5, "maxFiles": 7, "minAvgFileSizeMB": 32}}
    g = directlake_guardrails(contract)
    assert g == {"max_rows": 5, "max_files": 7, "min_avg_file_size_mb": 32}


def test_guardrails_reject_missing_block() -> None:
    # Direct Lake limits are per-SKU. A default would produce a false pass on a
    # small capacity, so an absent block must fail rather than fall back.
    try:
        directlake_guardrails({})
    except GuardrailsNotConfigured:
        return
    raise AssertionError("Expected GuardrailsNotConfigured")


def test_guardrails_reject_unset_limits() -> None:
    contract = {"directLake": {"maxRows": None, "maxFiles": None, "minAvgFileSizeMB": None}}
    try:
        directlake_guardrails(contract)
    except GuardrailsNotConfigured as exc:
        assert "maxFiles" in str(exc)
        return
    raise AssertionError("Expected GuardrailsNotConfigured")


def _run_all() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    _run_all()

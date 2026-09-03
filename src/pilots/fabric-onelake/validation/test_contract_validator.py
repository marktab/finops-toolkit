"""Smoke tests for the pilot contract validator.

Run: python -m pytest src/pilots/fabric-onelake/validation/test_contract_validator.py
or:  python src/pilots/fabric-onelake/validation/test_contract_validator.py
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from contract_validator import (
    ContractViolation,
    validate_batch_completeness,
    validate_compaction_sla,
    validate_focus_schema,
    validate_non_null,
    validate_row_conservation,
)

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
SCHEMA = CONTRACTS / "focus-schema.contract.json"
STORAGE = CONTRACTS / "storage-layout.contract.json"


def _good_columns() -> dict[str, str]:
    # Minimal set covering required columns with correct mapped types.
    return {
        "BilledCost": "decimal",
        "BillingAccountId": "string",
        "BillingAccountName": "string",
        "BillingAccountType": "string",
        "BillingCurrency": "string",
        "BillingPeriodEnd": "timestamp",
        "BillingPeriodStart": "timestamp",
        "ChargeCategory": "string",
        "ChargeDescription": "string",
        "ChargePeriodEnd": "timestamp",
        "ChargePeriodStart": "timestamp",
        "ContractedCost": "decimal",
        "EffectiveCost": "decimal",
        "ListCost": "decimal",
        "ProviderName": "string",
        "PublisherName": "string",
        "ServiceCategory": "string",
        "ServiceName": "string",
    }


def _expect(violation: bool, fn) -> None:
    try:
        fn()
    except ContractViolation:
        assert violation, "Unexpected ContractViolation"
        return
    assert not violation, "Expected ContractViolation but none raised"


def test_schema_passes_on_valid_input() -> None:
    result = validate_focus_schema(_good_columns(), "1.2", SCHEMA)
    assert result.warnings == []


def test_schema_warns_on_extra_column() -> None:
    cols = _good_columns()
    cols["x_SomeNewAugmentation"] = "string"
    result = validate_focus_schema(cols, "1.2", SCHEMA)
    assert any("extra" in w.lower() for w in result.warnings)


def test_schema_fails_on_focus_version_mismatch() -> None:
    _expect(True, lambda: validate_focus_schema(_good_columns(), "1.0", SCHEMA))


def test_schema_fails_on_missing_required_column() -> None:
    cols = _good_columns()
    del cols["EffectiveCost"]
    _expect(True, lambda: validate_focus_schema(cols, "1.2", SCHEMA))


def test_schema_fails_on_type_mismatch() -> None:
    cols = _good_columns()
    cols["BilledCost"] = "string"
    _expect(True, lambda: validate_focus_schema(cols, "1.2", SCHEMA))


def test_non_null_fails_on_null() -> None:
    _expect(True, lambda: validate_non_null({"EffectiveCost": 3}, SCHEMA))


def test_non_null_passes_when_clean() -> None:
    result = validate_non_null({"EffectiveCost": 0, "BilledCost": 0}, SCHEMA)
    assert result.warnings == []


def test_compaction_passes_within_sla() -> None:
    now = datetime.now(timezone.utc)
    metrics = {
        "lastRunTimestampUtc": (now - timedelta(hours=2)).isoformat(),
        "avgFileSizeMBAfter": 130,
        "smallFileFractionAfter": 0.02,
    }
    result = validate_compaction_sla(metrics, STORAGE, now=now)
    # Provisional Z-order should surface as a warning.
    assert any("provisional" in w.lower() for w in result.warnings)


def test_compaction_fails_when_stale() -> None:
    now = datetime.now(timezone.utc)
    metrics = {"lastRunTimestampUtc": (now - timedelta(hours=48)).isoformat()}
    _expect(True, lambda: validate_compaction_sla(metrics, STORAGE, now=now))


def test_compaction_fails_on_fragmentation() -> None:
    now = datetime.now(timezone.utc)
    metrics = {
        "lastRunTimestampUtc": now.isoformat(),
        "avgFileSizeMBAfter": 8,
        "smallFileFractionAfter": 0.5,
    }
    _expect(True, lambda: validate_compaction_sla(metrics, STORAGE, now=now))


def test_row_conservation_passes_when_equal() -> None:
    result = validate_row_conservation(1000, 1000, STORAGE, stage="staging->delta")
    assert result.warnings == []


def test_row_conservation_passes_on_empty_hop() -> None:
    # No data yet is conservation, not a violation.
    result = validate_row_conservation(0, 0, STORAGE, stage="ingestion->staging")
    assert result.warnings == []


def test_row_conservation_fails_when_rows_dropped() -> None:
    # The #2173 / #2180 class: rows silently lost across a hop.
    _expect(True, lambda: validate_row_conservation(1000, 800, STORAGE, stage="staging->delta"))


def test_row_conservation_fails_when_rows_added() -> None:
    # The #1736 class: a hop inventing rows.
    _expect(True, lambda: validate_row_conservation(1000, 1240, STORAGE, stage="staging->delta"))


def test_row_conservation_fails_on_negative_count() -> None:
    _expect(True, lambda: validate_row_conservation(-1, 0, STORAGE))


def test_batch_completeness_passes_when_equal() -> None:
    result = validate_batch_completeness(1000, 1000, STORAGE, stage="staging-read")
    assert result.warnings == []


def test_batch_completeness_fails_on_partial_read() -> None:
    # The cross-boundary #1625 / #2173 trap: consumed a subset of the batch.
    _expect(True, lambda: validate_batch_completeness(1000, 999, STORAGE, stage="staging-read"))


def test_batch_completeness_fails_on_excess_read() -> None:
    _expect(True, lambda: validate_batch_completeness(1000, 1001, STORAGE, stage="staging-read"))


def test_batch_completeness_fails_on_negative_count() -> None:
    _expect(True, lambda: validate_batch_completeness(-1, 0, STORAGE))


# --- column source integrity ------------------------------------------------ #


def test_pinned_hash_matches_the_column_source() -> None:
    # An unpinned or stale hash makes the integrity guard inert, which is how the
    # one check against upstream FOCUS drift silently stops working.
    contract = json.loads(SCHEMA.read_text(encoding="utf-8"))
    expected = contract["columnSource"]["integrity"]["expected"]
    assert expected, "Column-source integrity hash is not pinned."
    source = (SCHEMA.parent / contract["columnSource"]["path"]).resolve()
    actual = hashlib.sha256(source.read_bytes()).hexdigest()
    assert actual == expected, f"Pinned hash {expected} does not match {source.name} ({actual})."


def test_column_source_is_a_verbatim_copy_of_open_data() -> None:
    # The contract references open-data as the single source of truth. The copy
    # beside the contract exists only so notebooks can load it from Lakehouse
    # Files; if it drifts, the pilot validates against a schema the toolkit no
    # longer produces.
    contract = json.loads(SCHEMA.read_text(encoding="utf-8"))
    local = (SCHEMA.parent / contract["columnSource"]["path"]).resolve()
    upstream = Path(__file__).resolve().parents[4] / contract["columnSource"]["upstreamPath"]
    assert upstream.exists(), f"Upstream column source not found: {upstream}"
    assert local.read_bytes() == upstream.read_bytes(), (
        f"{local.name} has drifted from {contract['columnSource']['upstreamPath']}. "
        "Re-copy from open-data and re-pin the integrity hash."
    )


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

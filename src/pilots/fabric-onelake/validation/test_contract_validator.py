"""Smoke tests for the pilot contract validator.

Run: python -m pytest src/pilots/fabric-onelake/validation/test_contract_validator.py
or:  python src/pilots/fabric-onelake/validation/test_contract_validator.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from contract_validator import (
    ContractViolation,
    validate_compaction_sla,
    validate_focus_schema,
    validate_non_null,
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

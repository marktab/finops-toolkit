"""Standalone numeric acceptance policy, independent of a Spark installation."""

import sys
from pathlib import Path

import pytest

PILOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PILOT / "notebooks" / "lib"))
sys.path.insert(0, str(PILOT / "validation"))

from contract_validator import ContractViolation, validate_focus_schema
from focus_pilot.schema_bridge import numeric_storage_types, validate_numeric_target


def test_every_canonical_decimal_uses_exact_storage():
    import json

    source = json.loads((PILOT / "contracts" / "FocusCost_1.2-preview.json").read_text())
    fields = numeric_storage_types()
    decimals = {c["ColumnName"] for c in source["Columns"] if c["DataType"] == "Decimal"}
    assert decimals
    assert all(fields[name] == "decimal(38,18)" for name in decimals)


def test_float_is_not_relabelled_as_logical_decimal():
    import json

    contract_path = PILOT / "contracts" / "focus-schema.contract.json"
    contract = json.loads(contract_path.read_text())
    source = json.loads((contract_path.parent / "FocusCost_1.2-preview.json").read_text())
    fields = {c["ColumnName"]: contract["typeMapping"][c["DataType"]] for c in source["Columns"]}
    for name, logical in fields.items():
        if logical == "decimal":
            for unsupported in ("double", "string", "boolean"):
                changed = {**fields, name: unsupported}
                with pytest.raises(ContractViolation, match=f"{name}: expected decimal, got {unsupported}"):
                    validate_focus_schema(changed, "1.2", contract_path)


def test_existing_incompatible_numeric_target_fails():
    with pytest.raises(ContractViolation, match="explicitly approved"):
        validate_numeric_target({"BilledCost": "double"})
    with pytest.raises(ContractViolation, match="BilledCost"):
        validate_numeric_target({"BilledCost": "decimal(19,10)"})
    validate_numeric_target({"BilledCost": "decimal(38,18)", "Tags": "string"})
    with pytest.raises(ContractViolation, match="billedcost"):
        validate_numeric_target({"billedcost": "double"}, case_sensitive=False)


def test_shrink_floor_does_not_prove_scope_or_month_coverage():
    from focus_pilot.restatement import check_restatement_ratio

    # Missing a smaller scope/month is invisible to aggregate row conservation.
    check_restatement_ratio(100, 75, 0.5)


@pytest.mark.parametrize("invalid", [None, True, "36", 36.0])
def test_staging_count_must_be_an_integer(invalid):
    from contract_validator import validate_batch_completeness

    with pytest.raises(ContractViolation, match="non-null integer"):
        validate_batch_completeness(invalid, 36, PILOT / "contracts" / "storage-layout.contract.json")


def test_synthetic_manifest_is_independent_exact_and_multiscope():
    from decimal import Decimal
    from focus_pilot.synthetic import sample_fixture

    rows, logical, expected = sample_fixture()
    assert len(rows) == 36
    assert len(expected) == 12
    assert len([name for name, dtype in logical.items() if dtype == "decimal"]) > 4
    assert {r["chargeMonth"] for r in expected} == {"2025-04", "2025-05", "2025-06"}
    assert {r["scope"] for r in expected} == {"scope-a", "scope-b"}
    assert {r["currency"] for r in expected} == {"USD", "EUR"}
    assert all(r["rowCount"] == 3 for r in expected)
    assert all(Decimal(r["totals"]["BilledCost"]) == Decimal("12.220678901234567891") for r in expected)


def test_actual_write_notebook_refuses_missing_operator_acceptance_before_read():
    import ast

    path = PILOT / "notebooks" / "02_delta_write.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    parameters = {
        "_PILOT_ROOT": PILOT,
        "oneLakeEndpoint": "isolated-test",
        "ingestion_id": "known-batch",
        "acceptance_record_id": "",
    }
    # Execute only the preflight before the Spark import; append the actual
    # parameter guard, unchanged, without requiring a Spark installation.
    nodes = []
    guard = None
    for node in tree.body:
        if isinstance(node, ast.If) and "acceptance_record_id" in ast.unparse(node.test):
            guard = node
            break
        if isinstance(node, ast.ImportFrom) and node.module == "pyspark.sql":
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and (
            ast.unparse(node.value.func) == "spark.conf.set"
        ):
            continue
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in parameters for t in node.targets
        ):
            continue
        nodes.append(node)
    assert guard is not None
    tree.body = nodes + [guard]
    with pytest.raises(ValueError, match="independently accept"):
        exec(compile(tree, str(path), "exec"), parameters)

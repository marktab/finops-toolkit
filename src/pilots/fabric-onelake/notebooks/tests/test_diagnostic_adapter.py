"""Offline tests execute notebook 04's adapter and append path with a Spark double."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "notebooks" / "lib"))
sys.path.insert(0, str(ROOT / "validation"))

from contract_validator import ContractViolation, validate_compaction_sla
from focus_pilot.readiness import (
    append_layout_assessment,
    directlake_guardrails,
    evaluate_directlake_layout_precondition,
    read_latest_compaction_evidence,
)
from focus_pilot.schema_bridge import find_unsupported_directlake_types

NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
STORAGE = ROOT / "contracts" / "storage-layout.contract.json"
GATE = "_pilot_directlake_gate"
FIELDS = {
    "tableName": "string",
    "meetsLayoutPrecondition": "boolean",
    "checks": "string",
    "reasons": "string",
    "evaluatedAtUtc": "string",
}


def field(name, kind, nullable=True):
    return SimpleNamespace(
        name=name, dataType=SimpleNamespace(simpleString=lambda: kind), nullable=nullable
    )


def evidence(table="Costs", timestamp=None, **overrides):
    return {
        "tableName": table,
        "lastRunTimestampUtc": timestamp or (NOW - timedelta(hours=1)).isoformat(),
        "avgFileSizeMBAfter": 128.0,
        "smallFileFractionAfter": 0.0,
        "lastRunStatus": "success",
        **overrides,
    }


class Frame:
    def __init__(self, spark, rows=(), fields=(), metrics=False, filtered=False):
        self.spark, self.rows = spark, list(rows)
        self.schema = SimpleNamespace(fields=list(fields))
        self.metrics, self.filtered = metrics, filtered

    def where(self, predicate):
        self.spark.events.append(("filter", predicate))
        match = re.fullmatch(r"(lower\(tableName\)|tableName) = '([A-Za-z_][A-Za-z0-9_]*)'", predicate)
        assert match, predicate
        expression, target = match.groups()
        rows = [row for row in self.rows if isinstance(row.get("tableName"), str) and (
            row["tableName"].lower() if expression.startswith("lower") else row["tableName"]
        ) == target]
        return Frame(self.spark, rows, metrics=True, filtered=True)

    def collect(self):
        if self.metrics:
            assert self.filtered, "Unscoped metrics collection is forbidden"
            self.spark.events.append(("collect", len(self.rows)))
        return self.rows

    def count(self):
        return 100

    @property
    def write(self):
        return Writer(self.spark, self.rows)


class Writer:
    def __init__(self, spark, rows):
        self.spark, self.rows = spark, rows
        self.options = {}

    def format(self, value):
        assert value == "delta"
        return self

    def mode(self, value):
        assert value == "append"
        return self

    def option(self, key, value):
        self.options[key] = value
        return self

    def saveAsTable(self, table):
        assert table == GATE
        assert self.options == {"mergeSchema": "true"}
        if self.spark.write_error:
            raise self.spark.write_error
        self.spark.written.extend(self.rows)


class Spark:
    def __init__(self, rows=(), sensitive=False, gate_fields=None, catalog_names=("Costs",)):
        self.rows, self.gate_fields = rows, gate_fields
        self.events, self.written = [], []
        self.write_error = None
        self.conf = SimpleNamespace(get=lambda key: str(sensitive).lower())
        tables = [SimpleNamespace(name=name, isTemporary=False) for name in catalog_names]
        self.catalog = SimpleNamespace(
            listTables=lambda: tables,
            getTable=lambda name: next(table for table in tables if (
                table.name == name if sensitive else table.name.lower() == name.lower()
            )),
            tableExists=lambda name: (gate_fields is not None) if name == GATE else any(
                table.name == name if sensitive else table.name.lower() == name.lower()
                for table in tables
            ),
        )
        self.read = SimpleNamespace(table=self.read_metrics)

    def read_metrics(self, name):
        assert name == "_pilot_compaction_metrics"
        return Frame(self, self.rows, metrics=True)

    def table(self, name):
        if name == GATE:
            return Frame(self, fields=self.gate_fields)
        return SimpleNamespace(
            schema=[field("BilledCost", "double")], count=lambda: 100
        )

    def sql(self, query):
        assert query == "DESCRIBE DETAIL Costs"
        return Frame(self, [{"numFiles": 1, "sizeInBytes": 128 * 1024 * 1024}])

    def createDataFrame(self, rows, schema):
        assert "assessmentMetadata string" in schema
        return Frame(self, rows)


class Clock:
    @staticmethod
    def now(zone):
        assert zone == timezone.utc
        return NOW


def run_notebook(spark):
    """Run the actual executable assessment cells, not a copied adapter."""
    notebook = ROOT / "notebooks" / "04_directlake_precondition.py"
    tree = ast.parse(notebook.read_text(encoding="utf-8"))
    start = next(i for i, node in enumerate(tree.body) if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "guardrails" for target in node.targets))
    emitted = []
    scope = {
        "spark": spark, "storage_contract": {
            "directLake": {"maxRows": 1000, "maxFiles": 100, "minAvgFileSizeMB": 64}
        },
        "_STORAGE_CONTRACT": STORAGE, "datetime": Clock, "timezone": timezone,
        "json": json, "table_name": "Costs", "metrics_table": "_pilot_compaction_metrics",
        "gate_table": GATE,
        "notebookutils": SimpleNamespace(notebook=SimpleNamespace(exit=emitted.append)),
        **{function.__name__: function for function in (
            directlake_guardrails, evaluate_directlake_layout_precondition,
            read_latest_compaction_evidence, append_layout_assessment,
            find_unsupported_directlake_types, validate_compaction_sla, ContractViolation,
        )},
    }
    exec(compile(ast.Module(body=tree.body[start:], type_ignores=[]), str(notebook), "exec"), scope)
    return json.loads(emitted[0])


def test_notebook_uses_target_evidence_before_collecting():
    spark = Spark([
        evidence(timestamp=(NOW - timedelta(hours=27)).isoformat()),
        evidence("Other", NOW.isoformat()),
    ])
    result = run_notebook(spark)
    assert not result["checks"]["compaction_healthy"]
    assert spark.events == [("filter", "lower(tableName) = 'costs'"), ("collect", 1)]


def test_notebook_missing_target_does_not_borrow_other_table():
    result = run_notebook(Spark([evidence("Other", NOW.isoformat())]))
    assert not result["meets_precondition"]
    assert result["reasons"]


@pytest.mark.parametrize("timestamp", ["invalid", "2026-09-21T12:00:01Z", None, 123])
def test_actual_adapter_rejects_bad_or_future_timestamps(timestamp):
    row = evidence()
    row["lastRunTimestampUtc"] = timestamp
    with pytest.raises(ContractViolation):
        read_latest_compaction_evidence(Spark([row]), "Costs", "_pilot_compaction_metrics", now=NOW)


@pytest.mark.parametrize("timestamp", [
    "2026-09-21T11:00:00Z", "2026-09-21T13:00:00+02:00",
    "2026-09-21T11:00:00", datetime(2026, 9, 21, 11),
])
def test_utc_normalization_in_actual_adapter(timestamp):
    row = read_latest_compaction_evidence(
        Spark([evidence(timestamp=timestamp)]), "Costs", "_pilot_compaction_metrics", now=NOW
    )
    assert row["lastRunTimestampUtc"] == NOW - timedelta(hours=1)
    validate_compaction_sla(row, STORAGE, now=NOW.replace(tzinfo=None))


def test_latest_uses_utc_instead_of_lexical_timestamp_order():
    rows = [
        evidence(timestamp="2026-09-21T13:00:00+03:00", avgFileSizeMBAfter=1),
        evidence(timestamp="2026-09-21T10:30:00Z"),
    ]
    assert run_notebook(Spark(rows))["checks"]["compaction_healthy"]


def test_equivalent_ties_collapse_and_irrelevant_values_do_not_conflict():
    rows = [evidence(), evidence(timestamp="2026-09-21T13:00:00+02:00", bytesRewritten=19)]
    assert run_notebook(Spark(rows))["checks"]["compaction_healthy"]


@pytest.mark.parametrize("change", [
    {"avgFileSizeMBAfter": 256}, {"smallFileFractionAfter": 0.5}, {"lastRunStatus": "failed"},
])
@pytest.mark.parametrize("reverse", [False, True])
def test_conflicting_ties_fail_in_either_order(change, reverse):
    rows = [evidence(), evidence(timestamp="2026-09-21T13:00:00+02:00", **change)]
    with pytest.raises(ContractViolation, match="Conflicting"):
        read_latest_compaction_evidence(
            Spark(rows[::-1] if reverse else rows), "Costs", "_pilot_compaction_metrics", now=NOW
        )


@pytest.mark.parametrize("sensitive, expected", [(False, True), (True, False)])
def test_catalog_case_semantics_control_evidence_scope(sensitive, expected):
    result = run_notebook(Spark([evidence("costs")], sensitive=sensitive))
    assert result["checks"]["compaction_healthy"] is expected


def test_case_sensitive_distinct_table_cannot_supply_newer_evidence():
    rows = [evidence(timestamp=(NOW - timedelta(hours=27)).isoformat()), evidence("costs")]
    assert not run_notebook(Spark(rows, sensitive=True, catalog_names=("Costs", "costs")))["checks"]["compaction_healthy"]


@pytest.mark.parametrize("name", ["Lakehouse.Costs", "dbo.Costs", "`Costs`", "Costs; DROP TABLE Costs"])
def test_unsupported_qualified_or_escaped_identifiers_fail(name):
    with pytest.raises(ContractViolation, match="unqualified"):
        read_latest_compaction_evidence(Spark(), name, "_pilot_compaction_metrics", now=NOW)


def test_ambiguous_catalog_identity_fails():
    with pytest.raises(ContractViolation, match="ambiguous"):
        read_latest_compaction_evidence(
            Spark([evidence()], catalog_names=("Costs", "costs")),
            "Costs", "_pilot_compaction_metrics", now=NOW
        )


def test_catalog_case_resolution_disagreement_fails():
    spark = Spark([evidence()], sensitive=True)
    spark.catalog.tableExists = lambda name: True
    spark.catalog.getTable = lambda name: SimpleNamespace(name="Costs", isTemporary=False)
    with pytest.raises(ContractViolation, match="case resolution"):
        read_latest_compaction_evidence(spark, "Costs", "_pilot_compaction_metrics", now=NOW)


def test_invalid_older_target_evidence_is_not_hidden_by_latest_success():
    with pytest.raises(ContractViolation, match="Invalid"):
        read_latest_compaction_evidence(
            Spark([evidence(timestamp="invalid"), evidence()]),
            "Costs", "_pilot_compaction_metrics", now=NOW
        )


def test_other_tables_invalid_evidence_is_filtered_out():
    assert run_notebook(Spark([evidence("Other", "invalid"), evidence()]))["meets_precondition"]


def test_service_and_permission_failures_are_not_empty_data_success():
    spark = Spark()
    def denied(name):
        raise PermissionError("read denied")
    spark.read.table = denied
    with pytest.raises(PermissionError, match="read denied"):
        run_notebook(spark)
    assert not spark.written


@pytest.mark.parametrize("existing", ["fresh", "legacy", "current"])
def test_metadata_is_separate_and_append_compatible(existing):
    fields = None if existing == "fresh" else [field(name, kind) for name, kind in FIELDS.items()]
    if existing == "current":
        fields.append(field("assessmentMetadata", "string"))
    spark = Spark([evidence()], gate_fields=fields)
    historical = {"assessmentMetadata": None, "checks": '{"compaction_healthy":true}'}
    spark.written.append(historical.copy())
    result = run_notebook(spark)
    assert result["meets_precondition"]
    assert result["reasons"] == []
    assert all(type(value) is bool for value in result["checks"].values())
    assert result["assessmentMetadata"] == {
        "assessmentScope": "listedChecksOnly", "vOrderVerification": "notPerformed"
    }
    assert json.loads(spark.written[-1]["assessmentMetadata"]) == result["assessmentMetadata"]
    assert spark.written[0] == historical
    assert len(spark.written) == 2


@pytest.mark.parametrize("fields", [
    [field(name, "int" if name == "checks" else kind) for name, kind in FIELDS.items()],
    [field(name, kind) for name, kind in FIELDS.items()] + [field("unrelated", "string")],
    [field(name, kind) for name, kind in FIELDS.items()] + [field("assessmentMetadata", "string", False)],
])
def test_incompatible_gate_schema_fails_without_writing(fields):
    spark = Spark([evidence()], gate_fields=fields)
    with pytest.raises(ContractViolation, match="schema|nullable"):
        run_notebook(spark)
    assert not spark.written


def test_append_permission_error_is_explicit():
    spark = Spark([evidence()])
    spark.write_error = PermissionError("alter denied")
    with pytest.raises(PermissionError, match="alter denied"):
        run_notebook(spark)
    assert not spark.written


@pytest.mark.parametrize("hours, passes", [(26, True), (26.0001, False), (-0.01, False)])
def test_compaction_sla_preserves_26_hour_boundary(hours, passes):
    row = evidence(timestamp=NOW - timedelta(hours=hours))
    if passes:
        validate_compaction_sla(row, STORAGE, now=NOW)
    else:
        with pytest.raises(ContractViolation):
            validate_compaction_sla(row, STORAGE, now=NOW)


@pytest.mark.parametrize("change", [
    {"lastRunTimestampUtc": "not-a-time"}, {"lastRunTimestampUtc": None},
    {"avgFileSizeMBAfter": None}, {"avgFileSizeMBAfter": float("nan")},
    {"smallFileFractionAfter": None}, {"smallFileFractionAfter": float("inf")},
    {"lastRunStatus": "failed"},
])
def test_compaction_sla_rejects_invalid_evidence(change):
    with pytest.raises(ContractViolation):
        validate_compaction_sla(evidence(**change), STORAGE, now=NOW)


def test_retired_promotion_apis_and_files_are_absent():
    import focus_pilot

    for name in ("PromotionDecision", "ZorderRecommendation", "evaluate_directlake_promotion", "recommend_zorder"):
        assert not hasattr(focus_pilot, name)
    assert not (ROOT / "notebooks" / "05_promotion.py").exists()
    assert not (ROOT / "notebooks" / "lib" / "focus_pilot" / "promotion.py").exists()

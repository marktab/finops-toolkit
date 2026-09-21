"""Local Spark/Delta regression for the checked gate metadata append.

Requires Java and functioning native Hadoop support on Windows (or Linux CI),
plus pyspark and delta-spark. Collection is not proof of engine execution.
No Fabric resource is contacted. All test-owned tables use an isolated local
catalog database and project-local warehouse, removed after the module.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "notebooks" / "lib"))
sys.path.insert(0, str(ROOT / "validation"))

pytest.importorskip("pyspark", reason="pyspark not installed")
pytest.importorskip("delta", reason="delta-spark not installed")

from delta import configure_spark_with_delta_pip
from pyspark.sql import SparkSession

from contract_validator import ContractViolation
from focus_pilot.readiness import append_layout_assessment


LEGACY_SCHEMA = (
    "tableName STRING, meetsLayoutPrecondition BOOLEAN, checks STRING, "
    "reasons STRING, evaluatedAtUtc STRING"
)
METADATA = {"assessmentScope": "listedChecksOnly", "vOrderVerification": "notPerformed"}


def assessment(timestamp="2026-09-21T12:00:00+00:00"):
    return {
        "tableName": "Costs",
        "meetsLayoutPrecondition": True,
        "checks": json.dumps({"compaction_healthy": True}),
        "reasons": "[]",
        "evaluatedAtUtc": timestamp,
        "assessmentMetadata": json.dumps(METADATA),
    }


@pytest.fixture(scope="module")
def spark():
    identity = uuid4().hex
    directory = Path.cwd() / f".diagnostic-spark-{identity}"
    directory.mkdir()
    database = f"diagnostic_{identity}"
    session = None
    created = False
    try:
        builder = (
            SparkSession.builder.appName("focus-pilot-diagnostic")
            .master("local[1]")
            .config("spark.sql.warehouse.dir", (directory / "warehouse").as_uri())
            .config("spark.local.dir", str(directory / "local"))
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
            .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
            .config("spark.databricks.delta.schema.autoMerge.enabled", "false")
            .config("spark.sql.shuffle.partitions", "1")
        )
        session = configure_spark_with_delta_pip(builder).getOrCreate()
        session.sql(f"CREATE DATABASE {database} LOCATION '{(directory / 'database').as_uri()}'")
        created = True
        session.sql(f"USE {database}")
        yield session
    finally:
        try:
            if session is not None:
                if created:
                    session.sql("USE default")
                    session.sql(f"DROP DATABASE {database} CASCADE")
                session.stop()
        finally:
            shutil.rmtree(directory)


def test_fresh_gate_persists_nullable_metadata_and_boolean_json(spark):
    table = "fresh_gate"
    append_layout_assessment(spark, table, assessment())
    stored = spark.table(table)
    metadata_field = stored.schema["assessmentMetadata"]
    assert metadata_field.dataType.simpleString() == "string"
    assert metadata_field.nullable
    row = stored.collect()[0].asDict()
    assert json.loads(row["assessmentMetadata"]) == METADATA
    assert json.loads(row["checks"]) == {"compaction_healthy": True}
    assert type(json.loads(row["checks"])["compaction_healthy"]) is bool
    assert json.loads(row["reasons"]) == []
    assert spark.conf.get("spark.databricks.delta.schema.autoMerge.enabled") == "false"


def test_legacy_gate_adds_only_metadata_and_preserves_historical_rows(spark):
    table = "legacy_gate"
    historical = assessment("2026-09-20T12:00:00+00:00")
    historical.pop("assessmentMetadata")
    spark.createDataFrame([historical], schema=LEGACY_SCHEMA).write.format("delta").saveAsTable(table)
    before_fields = {
        field.name: (field.dataType.simpleString(), field.nullable)
        for field in spark.table(table).schema
    }

    append_layout_assessment(spark, table, assessment())

    rows = spark.table(table).orderBy("evaluatedAtUtc").collect()
    assert len(rows) == 2
    old = rows[0].asDict()
    assert old.pop("assessmentMetadata") is None
    assert old == historical
    assert json.loads(rows[1]["assessmentMetadata"]) == METADATA
    after_fields = {
        field.name: (field.dataType.simpleString(), field.nullable)
        for field in spark.table(table).schema
    }
    assert after_fields.pop("assessmentMetadata") == ("string", True)
    assert after_fields == before_fields
    assert spark.conf.get("spark.databricks.delta.schema.autoMerge.enabled") == "false"


def test_current_gate_supports_subsequent_append_without_rewriting_history(spark):
    table = "current_gate"
    first = assessment("2026-09-20T12:00:00+00:00")
    append_layout_assessment(spark, table, first)
    append_layout_assessment(spark, table, assessment())
    rows = spark.table(table).orderBy("evaluatedAtUtc").collect()
    assert len(rows) == 2
    assert rows[0].asDict() == first
    assert all(json.loads(row["assessmentMetadata"]) == METADATA for row in rows)


@pytest.mark.parametrize("schema, mutate", [
    (LEGACY_SCHEMA.replace("checks STRING", "checks INT"), lambda row: row.update(checks=1)),
    (LEGACY_SCHEMA + ", unrelated STRING", lambda row: row.update(unrelated="preserve")),
    (LEGACY_SCHEMA + ", assessmentMetadata INT", lambda row: row.update(assessmentMetadata=123)),
])
def test_incompatible_gate_is_unchanged_after_rejected_append(spark, schema, mutate):
    table = "incompatible_" + uuid4().hex
    existing = assessment()
    existing.pop("assessmentMetadata")
    mutate(existing)
    spark.createDataFrame([existing], schema=schema).write.format("delta").saveAsTable(table)
    before_schema = spark.table(table).schema
    before_rows = spark.table(table).collect()
    before_version = spark.sql(f"DESCRIBE HISTORY {table}").first()["version"]

    with pytest.raises(ContractViolation, match="incompatible schema"):
        append_layout_assessment(spark, table, assessment())

    assert spark.table(table).schema == before_schema
    assert spark.table(table).collect() == before_rows
    assert spark.sql(f"DESCRIBE HISTORY {table}").first()["version"] == before_version

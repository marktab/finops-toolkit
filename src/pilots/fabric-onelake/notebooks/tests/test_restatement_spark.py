"""Live-Delta proof that a re-run does not duplicate cost data.

This is the one behavioural test the pilot carries: the append-only write it
replaced multiplied BilledCost on every re-run while every per-hop row-count
check still balanced, so no amount of pure-logic testing could have caught it.
It exercises the shipped ``write_month_snapshot`` against a real Delta table.

Requires pyspark and delta-spark; skipped when either is absent so the rest of
the suite still runs anywhere Python does:

    pip install pyspark delta-spark
    python -m pytest src/pilots/fabric-onelake/notebooks/tests/test_restatement_spark.py
"""

from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "validation"))

pytest.importorskip("pyspark", reason="pyspark not installed")
pytest.importorskip("delta", reason="delta-spark not installed")

from delta import configure_spark_with_delta_pip  # noqa: E402
from pyspark.sql import SparkSession  # noqa: E402
from pyspark.sql import types as T  # noqa: E402

from focus_pilot.restatement import charge_month_predicate, write_month_snapshot  # noqa: E402

_TABLE = "costs_restatement_test"
_PARTITION = ["x_ChargeMonth"]

_SCHEMA = T.StructType(
    [
        T.StructField("ChargeDescription", T.StringType(), nullable=False),
        T.StructField("BilledCost", T.DecimalType(38, 18), nullable=False),
        T.StructField("x_ChargeMonth", T.DateType(), nullable=False),
    ]
)


@pytest.fixture(scope="module")
def spark(tmp_path_factory):
    warehouse = tmp_path_factory.mktemp("warehouse")
    builder = (
        SparkSession.builder.appName("focus-pilot-restatement")
        .master("local[1]")
        .config("spark.sql.warehouse.dir", str(warehouse))
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config(
            "spark.sql.catalog.spark_catalog",
            "org.apache.spark.sql.delta.catalog.DeltaCatalog",
        )
        .config("spark.sql.shuffle.partitions", "1")
    )
    session = configure_spark_with_delta_pip(builder).getOrCreate()
    yield session
    session.stop()


@pytest.fixture(autouse=True)
def _clean_table(spark):
    spark.sql(f"DROP TABLE IF EXISTS {_TABLE}")
    yield
    spark.sql(f"DROP TABLE IF EXISTS {_TABLE}")


def _batch(spark, month: date, rows: int, cost: float = 1.0):
    return spark.createDataFrame(
        [(f"charge-{i:04d}", Decimal(str(cost)), month) for i in range(rows)],
        schema=_SCHEMA,
    )


def _write(spark, df, months):
    write_month_snapshot(
        df,
        _TABLE,
        partition_columns=_PARTITION,
        table_exists=spark.catalog.tableExists(_TABLE),
        predicate=charge_month_predicate(months),
    )


def _total_cost(spark) -> Decimal:
    return spark.table(_TABLE).agg({"BilledCost": "sum"}).collect()[0][0]


def test_rerunning_the_same_batch_does_not_duplicate(spark) -> None:
    may = date(2025, 5, 1)
    batch = _batch(spark, may, rows=100, cost=2.0)

    _write(spark, batch, [may])
    _write(spark, batch, [may])

    assert spark.table(_TABLE).count() == 100
    assert _total_cost(spark) == Decimal("200")


def test_restated_month_replaces_rather_than_accumulates(spark) -> None:
    may = date(2025, 5, 1)

    _write(spark, _batch(spark, may, rows=100, cost=1.0), [may])
    # The open month is re-exported with more rows and corrected costs.
    _write(spark, _batch(spark, may, rows=150, cost=3.0), [may])

    assert spark.table(_TABLE).count() == 150
    assert _total_cost(spark) == Decimal("450")


def test_replace_is_scoped_to_the_batch_months(spark) -> None:
    april, may = date(2025, 4, 1), date(2025, 5, 1)

    _write(spark, _batch(spark, april, rows=40, cost=1.0), [april])
    _write(spark, _batch(spark, may, rows=60, cost=1.0), [may])
    # Restating May must leave the closed April month untouched.
    _write(spark, _batch(spark, may, rows=10, cost=1.0), [may])

    counts = {
        row["x_ChargeMonth"]: row["n"]
        for row in spark.sql(
            f"SELECT x_ChargeMonth, count(*) AS n FROM {_TABLE} GROUP BY x_ChargeMonth"
        ).collect()
    }
    assert counts == {april: 40, may: 10}


def test_multi_month_batch_replaces_every_month_it_covers(spark) -> None:
    april, may = date(2025, 4, 1), date(2025, 5, 1)

    _write(spark, _batch(spark, april, rows=40).union(_batch(spark, may, rows=60)), [april, may])
    _write(spark, _batch(spark, april, rows=5).union(_batch(spark, may, rows=7)), [april, may])

    assert spark.table(_TABLE).count() == 12


def test_incompatible_existing_table_and_empty_replacement_preserve_data(spark):
    from contract_validator import ContractViolation

    may = date(2025, 5, 1)
    original = _batch(spark, may, 2)
    original.withColumn("BilledCost", original.BilledCost.cast("double")).write.format(
        "delta"
    ).partitionBy(*_PARTITION).saveAsTable(_TABLE)
    with pytest.raises(ContractViolation, match="Incompatible existing"):
        _write(spark, original, [may])
    assert _total_cost(spark) == 2.0
    with pytest.raises(ContractViolation, match="Zero-row"):
        _write(spark, original.limit(0), [may])
    assert spark.table(_TABLE).count() == 2


@pytest.mark.parametrize("value,dtype", [
    (Decimal("0.0000000000000000001"), T.DecimalType(38, 19)),
    (Decimal("100000000000000000000"), T.DecimalType(38, 0)),
])
def test_decimal_rounding_and_overflow_fail_before_mutation(spark, value, dtype):
    from contract_validator import ContractViolation
    from focus_pilot.schema_bridge import prepare_numeric_frame

    df = spark.createDataFrame([(value,)], T.StructType([T.StructField("BilledCost", dtype)]))
    with pytest.raises(ContractViolation, match="overflow, rounding"):
        prepare_numeric_frame(df).collect()
    assert not spark.catalog.tableExists(_TABLE)


def test_exact_decimal_cast_preserves_nulls_and_fraction(spark):
    from focus_pilot.schema_bridge import prepare_numeric_frame

    df = spark.createDataFrame(
        [(Decimal("0.1250000000000000000"),), (None,)],
        T.StructType([T.StructField("ContractedUnitPrice", T.DecimalType(38, 19))]),
    )
    result = prepare_numeric_frame(df)
    assert result.schema["ContractedUnitPrice"].dataType == T.DecimalType(38, 18)
    assert [r[0] for r in result.collect()] == [Decimal("0.125"), None]


def _run_notebook(filename, spark, **parameters):
    """Execute shipped cells with only deployment parameters injected."""
    import ast

    root = Path(__file__).resolve().parents[2]
    parameters["_PILOT_ROOT"] = root
    tree = ast.parse((root / "notebooks" / filename).read_text(encoding="utf-8"))
    tree.body = [
        node for node in tree.body
        if not (
            isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in parameters for target in node.targets)
        )
    ]
    namespace = {"spark": spark, **parameters}
    exec(compile(tree, filename, "exec"), namespace)
    return namespace


def _fixture_frame(spark):
    from focus_pilot.synthetic import sample_fixture

    rows, logical, expected = sample_fixture()
    mapping = {"decimal": T.DecimalType(38, 18), "double": T.DoubleType(),
               "string": T.StringType(), "timestamp": T.TimestampType(), "boolean": T.BooleanType()}
    schema = T.StructType([T.StructField(name, mapping[dtype]) for name, dtype in logical.items()])
    return spark.createDataFrame(rows, schema), expected


def test_parquet_ingestion_write_replay_and_corrections(spark, tmp_path):
    from pyspark.sql import functions as F
    from focus_pilot.schema_bridge import numeric_storage_types

    endpoint = str(tmp_path)
    source = str(tmp_path / "source")
    ledger = "_pilot_numeric_test_ledger"
    df, expected = _fixture_frame(spark)
    df.write.parquet(source)

    def ingest_write(path, batch):
        _run_notebook("01_ingestion.py", spark, source_path=path,
                      oneLakeEndpoint=endpoint, ingestion_id=batch)
        spark.conf.set("spark.sql.session.timeZone", "America/Los_Angeles")
        _run_notebook("02_delta_write.py", spark, oneLakeEndpoint=endpoint,
                      ingestion_id=batch, acceptance_record_id="synthetic-operator-record",
                      table_name=_TABLE, ledger_table=ledger)
        assert spark.conf.get("spark.sql.session.timeZone") == "UTC"

    try:
        ingest_write(source, "baseline")
        _run_notebook("02_delta_write.py", spark, oneLakeEndpoint=endpoint,
                      ingestion_id="baseline", acceptance_record_id="synthetic-replay-record",
                      table_name=_TABLE, ledger_table=ledger)
        target = spark.table(_TABLE)
        numeric = numeric_storage_types()
        assert all(target.schema[name].dataType.simpleString() == dtype for name, dtype in numeric.items())
        decimals = [name for name, dtype in numeric.items() if dtype.startswith("decimal")]
        groups = target.groupBy("x_ChargeMonth", "SubAccountId", "BillingCurrency").agg(
            F.count("*").alias("rowCount"), *[F.sum(name).alias(name) for name in decimals]
        ).collect()
        actual = {(r.x_ChargeMonth.strftime("%Y-%m"), r.SubAccountId, r.BillingCurrency): r for r in groups}
        for group in expected:
            row = actual[(group["chargeMonth"], group["scope"], group["currency"])]
            assert row.rowCount == group["rowCount"]
            assert all(row[name] == Decimal(total) for name, total in group["totals"].items())

        # Complete open-month, then closed-month corrections; other months unchanged.
        for month in (6, 4):
            before = spark.table(_TABLE).where(F.month("ChargePeriodStart") != month).orderBy(
                "ChargeDescription"
            ).collect()
            corrected = df.where(F.month("ChargePeriodStart") == month).withColumn(
                "BilledCost", F.lit(Decimal("-0.0001")).cast("decimal(38,18)")
            )
            path = str(tmp_path / f"correction-{month}")
            corrected.write.parquet(path)
            ingest_write(path, f"correction-{month}")
            assert spark.table(_TABLE).where(F.month("ChargePeriodStart") != month).orderBy(
                "ChargeDescription"
            ).collect() == before
            total = spark.table(_TABLE).where(F.month("ChargePeriodStart") == month).agg(
                F.sum("BilledCost")
            ).first()[0]
            assert total == Decimal("-0.0012")
        assert spark.table(_TABLE).count() == 36
    finally:
        spark.sql(f"DROP TABLE IF EXISTS {ledger}")


def test_double_parquet_rejected_by_actual_ingestion_notebook(spark, tmp_path):
    from contract_validator import ContractViolation

    df, _ = _fixture_frame(spark)
    may = date(2025, 5, 1)
    _write(spark, _batch(spark, may, 2), [may])
    source = str(tmp_path / "double-source")
    df.withColumn("BilledCost", df.BilledCost.cast("double")).write.parquet(source)
    with pytest.raises(ContractViolation, match="BilledCost: expected decimal, got double"):
        _run_notebook("01_ingestion.py", spark, source_path=source,
                      oneLakeEndpoint=str(tmp_path), ingestion_id="double-rejected")
    assert spark.table(_TABLE).count() == 2
    assert _total_cost(spark) == Decimal("2")
    assert not (tmp_path / "Files" / "_staging" / "double-rejected").exists()


def test_staging_truncation_rejected_by_actual_write_notebook(spark, tmp_path):
    from contract_validator import ContractViolation

    df, _ = _fixture_frame(spark)
    df.limit(1).write.parquet(str(tmp_path / "Files" / "_staging" / "truncated"))
    spark.createDataFrame([{
        "ingestionId": "truncated", "expectedRowCount": 36, "focusVersion": "1.2"
    }]).write.json(str(tmp_path / "Files" / "_staging" / "truncated_manifest"))
    may = date(2025, 5, 1)
    _write(spark, _batch(spark, may, 2), [may])
    with pytest.raises(ContractViolation, match="Incomplete batch"):
        _run_notebook("02_delta_write.py", spark, oneLakeEndpoint=str(tmp_path),
                      ingestion_id="truncated", acceptance_record_id="synthetic-record",
                      table_name=_TABLE)
    assert spark.table(_TABLE).count() == 2


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_number_fields_are_rejected(spark, value):
    from contract_validator import ContractViolation
    from focus_pilot.schema_bridge import numeric_storage_types, prepare_numeric_frame

    number_fields = [name for name, dtype in numeric_storage_types().items() if dtype == "double"]
    assert number_fields
    schema = T.StructType([T.StructField(name, T.DoubleType()) for name in number_fields])
    df = spark.createDataFrame([tuple(value for _ in number_fields)], schema)
    with pytest.raises(ContractViolation, match="non-finite"):
        prepare_numeric_frame(df)

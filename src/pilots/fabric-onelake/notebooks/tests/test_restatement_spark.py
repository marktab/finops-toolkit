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
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))

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
        T.StructField("BilledCost", T.DoubleType(), nullable=False),
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
        [(f"charge-{i:04d}", cost, month) for i in range(rows)],
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


def _total_cost(spark) -> float:
    return spark.table(_TABLE).agg({"BilledCost": "sum"}).collect()[0][0]


def test_rerunning_the_same_batch_does_not_duplicate(spark) -> None:
    may = date(2025, 5, 1)
    batch = _batch(spark, may, rows=100, cost=2.0)

    _write(spark, batch, [may])
    _write(spark, batch, [may])

    assert spark.table(_TABLE).count() == 100
    assert _total_cost(spark) == pytest.approx(200.0)


def test_restated_month_replaces_rather_than_accumulates(spark) -> None:
    may = date(2025, 5, 1)

    _write(spark, _batch(spark, may, rows=100, cost=1.0), [may])
    # The open month is re-exported with more rows and corrected costs.
    _write(spark, _batch(spark, may, rows=150, cost=3.0), [may])

    assert spark.table(_TABLE).count() == 150
    assert _total_cost(spark) == pytest.approx(450.0)


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

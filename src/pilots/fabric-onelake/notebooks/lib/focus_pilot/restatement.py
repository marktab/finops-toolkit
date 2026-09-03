"""Restatement semantics for the Delta write (Decision 2).

Cost Management restates: the open charge month is re-exported every day, and
closed months receive later credit and amortization corrections. Each batch is
therefore a full snapshot of the months it covers, and the write replaces those
months rather than appending to them.

The predicate construction and the shrink guard live here so both are testable
without a Spark session; the notebook supplies the observed month list and the
before/after row counts.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable, Sequence


class ImplausibleRestatement(Exception):
    """A restatement removed far more rows than it wrote."""


def charge_month_predicate(
    months: Sequence[date],
    column: str = "x_ChargeMonth",
) -> str:
    """Build the ``replaceWhere`` predicate for the batch's charge months.

    Args:
        months: Distinct charge months present in the batch.
        column: Partition column holding the month.

    Returns:
        A Delta ``replaceWhere`` predicate restricted to those months.

    Raises:
        ValueError: on an empty month list. An empty predicate would either
            replace nothing or, worse, match everything; neither is a safe
            interpretation of "the batch covered no months".
    """
    if not months:
        raise ValueError(
            "Batch contains no charge months; refusing to build a replace predicate."
        )
    literals = ", ".join(f"DATE'{month:%Y-%m-%d}'" for month in sorted(months))
    return f"{column} in ({literals})"


def check_restatement_ratio(
    rows_removed: int,
    rows_written: int,
    min_ratio: float | None,
    months: Iterable[date] = (),
) -> None:
    """Reject a restatement that replaces a month with a fragment of itself.

    ``replaceWhere`` cannot distinguish a genuine correction from a truncated
    source export, and a truncated export silently deletes good months. A
    month's row count effectively never halves between exports, so a large drop
    means the source is incomplete.

    Args:
        rows_removed: Rows the replace deleted from the target months.
        rows_written: Rows the batch wrote in their place.
        min_ratio: Minimum written/removed ratio to accept, or None to skip the
            check (for an intentional historical re-scope).
        months: Charge months involved, used only in the error message.

    Raises:
        ImplausibleRestatement: when the ratio floor is breached.
    """
    if min_ratio is None or rows_removed <= 0:
        return
    if rows_written >= rows_removed * min_ratio:
        return

    scope = ", ".join(f"{m:%Y-%m}" for m in sorted(months)) or "the target month(s)"
    raise ImplausibleRestatement(
        f"Restatement removed {rows_removed} row(s) but wrote only {rows_written} "
        f"for {scope}. That is below the {min_ratio:.0%} floor and usually means a "
        "truncated source export. Verify the export and re-run, or set the ratio to "
        "None if this reduction is intentional."
    )


def write_month_snapshot(
    df,
    table_name: str,
    *,
    partition_columns: Sequence[str],
    table_exists: bool,
    predicate: str,
) -> None:
    """Write the batch as a full snapshot of the charge months it covers.

    On an existing table this is a ``replaceWhere`` overwrite scoped to those
    months: months outside the predicate are untouched, and re-running the same
    batch is a no-op rather than a duplication. On first run the table does not
    exist yet, so the same overwrite simply creates it - ``replaceWhere`` is
    omitted because there is nothing to scope the replace against.

    Kept duck-typed (no pyspark import) so this module stays importable, and
    unit-testable, without a Spark installation.

    Args:
        df: DataFrame to write, already carrying the partition column.
        table_name: Target managed Delta table.
        partition_columns: Partition columns from the D2 contract.
        table_exists: Whether the target table already exists.
        predicate: Month predicate from :func:`charge_month_predicate`.
    """
    writer = (
        df.write.format("delta")
        .mode("overwrite")
        .partitionBy(*partition_columns)
        .option("mergeSchema", "true")
    )
    if table_exists:
        writer = writer.option("replaceWhere", predicate)
    writer.saveAsTable(table_name)

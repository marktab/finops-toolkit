"""File-layout metrics for the compaction notebook.

Computing the metrics from a list of file sizes is pure and unit-testable; the
notebook supplies the sizes by listing the Delta table's parquet files before
and after OPTIMIZE.
"""

from __future__ import annotations

from dataclasses import dataclass

_MB = 1024 * 1024


@dataclass(frozen=True)
class FileMetrics:
    """Summary of a Delta table's parquet file layout at a point in time."""

    file_count: int
    avg_file_size_mb: float
    small_file_fraction: float
    total_bytes: int


def compute_file_metrics(
    file_sizes_bytes: list[int],
    small_file_threshold_mb: float,
) -> FileMetrics:
    """Compute layout metrics from a list of parquet file sizes.

    Args:
        file_sizes_bytes: Size in bytes of each data file in the table.
        small_file_threshold_mb: Files at or below this size count as "small".

    Returns:
        FileMetrics. An empty table yields zeros (and a small_file_fraction of
        0.0), which the SLA check treats as "no data yet", not a violation.
    """
    count = len(file_sizes_bytes)
    if count == 0:
        return FileMetrics(0, 0.0, 0.0, 0)

    total = sum(file_sizes_bytes)
    threshold_bytes = small_file_threshold_mb * _MB
    small = sum(1 for size in file_sizes_bytes if size <= threshold_bytes)

    return FileMetrics(
        file_count=count,
        avg_file_size_mb=round((total / count) / _MB, 3),
        small_file_fraction=round(small / count, 4),
        total_bytes=total,
    )

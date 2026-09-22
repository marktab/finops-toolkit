"""File-layout metrics for the compaction notebook.

Computing the metrics from a list of file sizes is pure and unit-testable; the
notebook supplies the sizes by listing the Delta table's parquet files before
and after OPTIMIZE.

OPTIMIZE does not delete the files it replaces - they remain on disk until
VACUUM. A plain filesystem listing therefore counts both generations and reports
a compacted table as fragmented, so the notebook intersects its listing with the
Delta log's active file set (``DataFrame.inputFiles()``) before computing
metrics. ``select_active_file_sizes`` is that intersection, kept pure so the
path-normalization rules are testable without a cluster.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
from urllib.parse import unquote, urlsplit

_MB = 1024 * 1024


class ActiveFileMismatch(Exception):
    """A listing and the Delta log's active set had no paths in common."""


def _normalize_path(path: str) -> str:
    """Reduce a file URI to a comparable path.

    ``inputFiles()`` and a ``binaryFile`` listing can report the same file with
    different schemes, hosts, or percent-encoding, so both sides are reduced to
    the decoded path component. Case is preserved: OneLake paths are
    case-sensitive.
    """
    return unquote(urlsplit(str(path)).path).rstrip("/")


def select_active_file_sizes(
    listed_files: Iterable[tuple[str, int]],
    active_paths: Iterable[str],
) -> list[int]:
    """Return sizes for only the listed files still active in the Delta log.

    Args:
        listed_files: (path, size_in_bytes) for every parquet file found under
            the table location, including files OPTIMIZE has superseded.
        active_paths: File URIs the Delta log currently considers part of the
            table, from ``DataFrame.inputFiles()``.

    Returns:
        Sizes of the active files only. Empty when the table has no active
        files (an empty table), which the SLA check treats as "no data yet".

    Raises:
        ActiveFileMismatch: when both inputs are non-empty but share no paths.
            That means normalization failed rather than that the table is empty,
            and silently reporting zero files would hand the SLA check and the
            readiness gate a fabricated result.
    """
    listed = [(_normalize_path(path), size) for path, size in listed_files]
    active = {_normalize_path(path) for path in active_paths}

    if not active:
        return []

    sizes = [size for path, size in listed if path in active]
    if listed and not sizes:
        raise ActiveFileMismatch(
            f"None of the {len(listed)} listed parquet file(s) matched the "
            f"{len(active)} file(s) the Delta log reports as active. Path "
            "normalization failed; refusing to report a fabricated file count."
        )
    return sizes


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

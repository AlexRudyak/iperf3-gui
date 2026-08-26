"""CSV export of sweep results.

Kept out of the window class so that the file format can be tested without a
GUI, and so the window is not responsible for disk I/O.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterable, Sequence
from pathlib import Path

from .metrics import RESULT_COLUMNS, IterationResult

logger = logging.getLogger(__name__)


class ExportError(RuntimeError):
    """Raised when results could not be written to disk."""


def write_results_csv(
    path: str | Path,
    results: Iterable[IterationResult],
    columns: Sequence[str] | None = None,
) -> int:
    """Write ``results`` to ``path`` as CSV.

    Args:
        path: destination file, overwritten if it exists.
        results: the rows to write.
        columns: subset of :data:`RESULT_COLUMNS` to include, in canonical
            order; defaults to all of them.

    Returns:
        The number of data rows written.

    Raises:
        ExportError: if a column is unknown or the file cannot be written.
    """
    selected = list(columns) if columns is not None else list(RESULT_COLUMNS)
    if not selected:
        raise ExportError("No columns were selected for export.")

    unknown = [name for name in selected if name not in RESULT_COLUMNS]
    if unknown:
        raise ExportError(f"Unknown column(s): {', '.join(unknown)}")

    rows = [result.as_row() for result in results]

    try:
        # newline="" is required by the csv module to avoid blank rows on
        # Windows; the encoding is pinned so non-ASCII values do not depend on
        # the machine's code page.
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=selected, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow({name: row.get(name) for name in selected})
    except OSError as exc:
        raise ExportError(f"Could not write {path}: {exc}") from exc

    logger.info("Exported %d sweep result(s) to %s", len(rows), path)
    return len(rows)

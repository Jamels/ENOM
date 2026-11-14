"""Small, quality-aware summaries of selected Mars 2020 MEDA CSV products."""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable
from typing import Any

import numpy as np


def summarize_product(
    csv_text: str,
    *,
    sensor: str,
    value_column: str,
    value_name: str,
    units: str,
    uncertainty_column: str | None = None,
    uncertainty_units: str | None = None,
    required_flags: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Summarize one PDS derived sensor column without retaining its raw table.

    Empty cells, non-finite values, and PDS's 999999999 fill value are excluded.
    The reported value is the median of valid rows from one Martian sol. It is a
    descriptive sample summary, not a climate normal or cross-site score.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames or value_column not in reader.fieldnames:
        raise ValueError(f"PDS {sensor} product is missing column {value_column}")
    if uncertainty_column and uncertainty_column not in reader.fieldnames:
        raise ValueError(f"PDS {sensor} product is missing {uncertainty_column}")
    for column in (required_flags or {}):
        if column not in reader.fieldnames:
            raise ValueError(f"PDS {sensor} product is missing quality flag {column}")

    values: list[float] = []
    uncertainties: list[float] = []
    row_count = 0
    eligible_row_count = 0
    for row in reader:
        row_count += 1
        if any(row.get(column) != expected for column, expected in (required_flags or {}).items()):
            continue
        eligible_row_count += 1
        value = _finite_pds_number(row.get(value_column))
        if value is None:
            continue
        values.append(value)
        if uncertainty_column:
            uncertainty = _finite_pds_number(row.get(uncertainty_column))
            if uncertainty is not None and uncertainty >= 0:
                uncertainties.append(uncertainty)

    if not values:
        raise ValueError(f"PDS {sensor} product has no valid {value_column} values")
    sample = np.asarray(values, dtype=np.float64)
    measurement: dict[str, Any] = {
        "name": value_name,
        "value": float(np.median(sample)),
        "units": units,
        "availability": "available",
        "summary_statistic": "median",
        "sample_count": len(values),
        "source_row_count": row_count,
        "invalid_value_count": eligible_row_count - len(values),
        "quality_filtered_row_count": row_count - eligible_row_count,
        "sample_percentiles": {
            "p10": float(np.percentile(sample, 10)),
            "p90": float(np.percentile(sample, 90)),
        },
        "sample_range": {"minimum": float(np.min(sample)), "maximum": float(np.max(sample))},
        "uncertainty": {
            "value": float(np.median(uncertainties)) if uncertainties else None,
            "units": uncertainty_units or units,
            "description": (
                f"Median reported per-row {sensor} uncertainty; not an uncertainty "
                "interval for the sol median."
                if uncertainties
                else "No valid per-row uncertainty values were supplied."
            ),
        },
    }
    return measurement


def _finite_pds_number(value: object) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    if not math.isfinite(number) or abs(number) >= 1e8:
        return None
    return number


def validate_sol_rows(csv_text: str, sol: int) -> int:
    """Check the product contains rows for the requested LMST sol."""
    rows: Iterable[dict[str, str]] = csv.DictReader(io.StringIO(csv_text))
    count = 0
    prefix = f"{sol:05d}M"
    for row in rows:
        local_time = row.get("LMST", "")
        if not local_time.startswith(prefix):
            raise ValueError(f"PDS product contains a row outside LMST sol {sol}")
        count += 1
    if count == 0:
        raise ValueError(f"PDS product contains no rows for LMST sol {sol}")
    return count

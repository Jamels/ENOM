"""Summarize daily ERA5 point samples returned by the Open-Meteo archive."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from statistics import mean
from typing import Any, TypeGuard

DATASET_ID = "era5-earth-candidate-climatology"
MODEL_NAME = "ERA5"
BASELINE_START = "1991-01-01"
BASELINE_END = "2020-12-31"
MONTHS = tuple(f"{month:02d}" for month in range(1, 13))


def _finite(value: Any) -> TypeGuard[int | float]:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def summarize_daily_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Return monthly climatologies while preserving actual returned grid coords."""
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise ValueError("ERA5 response has no daily measurements")
    dates = daily.get("time")
    if not isinstance(dates, list) or not dates:
        raise ValueError("ERA5 response has no daily dates")
    variable_names = {
        "temperature_2m_mean": "temperature_2m_mean",
        "wind_speed_10m_mean": "wind_speed_10m_mean",
        "precipitation_sum": "precipitation_sum",
    }
    if any(
        not isinstance(daily.get(name), list) or len(daily[name]) != len(dates)
        for name in variable_names.values()
    ):
        raise ValueError("ERA5 response daily columns have inconsistent lengths")
    monthly_values: dict[str, dict[str, list[float]]] = {
        key: defaultdict(list) for key in variable_names
    }
    annual_precipitation: dict[int, float] = defaultdict(float)
    monthly_precipitation_by_year: dict[tuple[int, str], float] = defaultdict(float)
    monthly_precipitation_counts: dict[str, set[int]] = defaultdict(set)
    valid_counts = {key: 0 for key in variable_names}
    for index, raw_date in enumerate(dates):
        parsed_date = date.fromisoformat(str(raw_date))
        month = f"{parsed_date.month:02d}"
        values = {key: daily[column][index] for key, column in variable_names.items()}
        for key in ("temperature_2m_mean", "wind_speed_10m_mean"):
            if _finite(values[key]):
                monthly_values[key][month].append(float(values[key]))
                valid_counts[key] += 1
        if _finite(values["precipitation_sum"]):
            precipitation = max(0.0, float(values["precipitation_sum"]))
            monthly_precipitation_by_year[(parsed_date.year, month)] += precipitation
            annual_precipitation[parsed_date.year] += precipitation
            monthly_precipitation_counts[month].add(parsed_date.year)
            valid_counts["precipitation_sum"] += 1
    for (_year, month), total in monthly_precipitation_by_year.items():
        monthly_values["precipitation_sum"][month].append(total)
    means = {
        key: {
            month: mean(monthly_values[key][month]) if monthly_values[key][month] else None
            for month in MONTHS
        }
        for key in variable_names
    }
    annual_temperature = [
        value for rows in monthly_values["temperature_2m_mean"].values() for value in rows
    ]
    annual_wind_kmh = [
        value for rows in monthly_values["wind_speed_10m_mean"].values() for value in rows
    ]
    annual_precipitation_values = list(annual_precipitation.values())
    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    if not _finite(latitude) or not _finite(longitude):
        raise ValueError("ERA5 response has no valid nearest-grid coordinates")
    return {
        "dataset_id": DATASET_ID,
        "model": MODEL_NAME,
        "requested_period": {"start": BASELINE_START, "end": BASELINE_END},
        "returned_period": {"start": str(dates[0]), "end": str(dates[-1])},
        "grid_point": {
            "latitude_deg": float(latitude),
            "longitude_east_deg": float(longitude) % 360.0,
        },
        "grid_elevation_m": float(payload["elevation"])
        if _finite(payload.get("elevation"))
        else None,
        "nominal_grid_spacing_deg": 0.25,
        "measurements": [
            {
                "name": "ERA5 monthly mean 2 m air temperature",
                "value": mean(annual_temperature) if annual_temperature else None,
                "units": "°C",
                "monthly_values": means["temperature_2m_mean"],
                "availability": "available" if annual_temperature else "not_observed",
                "sample_count": valid_counts["temperature_2m_mean"],
                "summary_statistic": (
                    "Mean of daily 2 m temperatures by calendar month across the "
                    "available 1991–2020 baseline"
                ),
            },
            {
                "name": "ERA5 monthly mean 10 m wind speed",
                "value": mean(annual_wind_kmh) / 3.6 if annual_wind_kmh else None,
                "units": "m/s",
                "monthly_values": {
                    month: value / 3.6 if value is not None else None
                    for month, value in means["wind_speed_10m_mean"].items()
                },
                "availability": "available" if annual_wind_kmh else "not_observed",
                "sample_count": valid_counts["wind_speed_10m_mean"],
                "summary_statistic": (
                    "Mean of daily ERA5 10 m wind speeds; Open-Meteo km/h values converted to m/s"
                ),
            },
            {
                "name": "ERA5 average monthly precipitation total",
                "value": mean(
                    value for value in means["precipitation_sum"].values() if value is not None
                )
                if valid_counts["precipitation_sum"]
                else None,
                "units": "mm/month",
                "monthly_values": means["precipitation_sum"],
                "availability": "available"
                if valid_counts["precipitation_sum"]
                else "not_observed",
                "sample_count": valid_counts["precipitation_sum"],
                "summary_statistic": (
                    "Mean monthly total precipitation across available years in the "
                    "1991–2020 baseline"
                ),
            },
        ],
        "mean_annual_precipitation_mm": mean(annual_precipitation_values)
        if annual_precipitation_values
        else None,
    }

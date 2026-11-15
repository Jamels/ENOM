import json
from pathlib import Path

import pytest

from twinworld import era5
from twinworld.analogue import discover, source_inventory
from twinworld.api import dataset_coverage, datasets

ROOT = Path(__file__).resolve().parents[1]


def test_daily_response_becomes_monthly_temperature_wind_and_precipitation_context():
    payload = {
        "latitude": -24.75,
        "longitude": 15.25,
        "elevation": 613,
        "daily": {
            "time": ["1991-01-01", "1991-01-02", "1991-02-01"],
            "temperature_2m_mean": [10, 20, 30],
            "wind_speed_10m_mean": [3.6, 7.2, 10.8],
            "precipitation_sum": [1, 3, 2],
        },
    }
    result = era5.summarize_daily_response(payload)
    temperature, wind, precipitation = result["measurements"]
    assert result["grid_point"] == {"latitude_deg": -24.75, "longitude_east_deg": 15.25}
    assert temperature["value"] == pytest.approx(20)
    assert temperature["monthly_values"]["01"] == pytest.approx(15)
    assert wind["value"] == pytest.approx(2)
    assert wind["monthly_values"]["01"] == pytest.approx(1.5)
    assert precipitation["monthly_values"]["01"] == pytest.approx(4)
    assert precipitation["monthly_values"]["02"] == pytest.approx(2)
    assert result["mean_annual_precipitation_mm"] == pytest.approx(6)


def test_invalid_or_missing_daily_columns_fail_clearly():
    with pytest.raises(ValueError, match="no daily dates"):
        era5.summarize_daily_response({"daily": {"time": []}})
    with pytest.raises(ValueError, match="inconsistent lengths"):
        era5.summarize_daily_response(
            {
                "daily": {
                    "time": ["1991-01-01"],
                    "temperature_2m_mean": [],
                    "wind_speed_10m_mean": [1],
                    "precipitation_sum": [1],
                }
            }
        )


def test_era5_source_is_context_in_all_three_earth_dimensions():
    result = discover(ROOT, "moon-shackleton-rim", "polar_resources")
    for dimension_id, expected_name in [
        ("thermal_illumination", "ERA5 monthly mean 2 m air temperature"),
        ("dust_processes", "ERA5 monthly mean 10 m wind speed"),
        ("water_resources", "ERA5 average monthly precipitation total"),
    ]:
        dimension = next(
            row for row in result["results"][0]["dimension_scores"] if row["id"] == dimension_id
        )
        assert dimension["score"] is None
        assert any(
            measurement["name"] == expected_name for measurement in dimension["measurements"]
        )

    site = discover(ROOT, "mars-jezero", "polar_resources")
    earth = next(row for row in site["results"] if row["place"]["id"] == "earth-namib")
    for dimension_id, expected_name in [
        ("thermal_illumination", "ERA5 monthly mean 2 m air temperature"),
        ("dust_processes", "ERA5 monthly mean 10 m wind speed"),
        ("water_resources", "ERA5 average monthly precipitation total"),
    ]:
        dimension = next(row for row in earth["dimension_scores"] if row["id"] == dimension_id)
        assert any(
            measurement["name"] == expected_name for measurement in dimension["measurements"]
        )
        assert dimension["score"] is None

    payload = json.loads(
        (ROOT / "data/environment/era5-earth-candidate-climatology.json").read_text()
    )
    assert len(payload["records"]) == 8
    assert all(
        record["location_precision"] == "nearest_era5_0.25_degree_grid_point"
        for record in payload["records"]
    )
    coverage = dataset_coverage(era5.DATASET_ID)
    assert coverage["unique_place_count"] == 8
    source = next(row for row in source_inventory(ROOT) if row["id"] == "era5-temperature")
    assert source["coverage_count"] == 8 and source["status"] == "operational"
    registry = next(row for row in datasets() if row["id"] == era5.DATASET_ID)
    assert registry["coverage_count"] == 8

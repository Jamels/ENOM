"""Cache small ERA5 climate summaries for the existing Earth candidate places."""

from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path

import requests

from twinworld import era5

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "data/manifests/candidate-locations.json"
OUTPUT = ROOT / "data/environment/era5-earth-candidate-climatology.json"
ENDPOINT = "https://archive-api.open-meteo.com/v1/archive"
PROVIDER_URL = "https://open-meteo.com/en/docs/historical-weather-api"
VARIABLES = ("temperature_2m_mean", "wind_speed_10m_mean", "precipitation_sum")


def main() -> None:
    entries = json.loads(CATALOGUE.read_text(encoding="utf-8"))["entries"]
    sites = [row for row in entries if row.get("body") == "earth"]
    session = requests.Session()
    session.headers.update({"User-Agent": "ENOM science data/1.0"})
    params = {
        "latitude": ",".join(str(site["latitude_deg"]) for site in sites),
        "longitude": ",".join(
            str(((float(site["longitude_east_deg"]) + 180.0) % 360.0) - 180.0) for site in sites
        ),
        "start_date": era5.BASELINE_START,
        "end_date": era5.BASELINE_END,
        "daily": ",".join(VARIABLES),
        "timezone": "UTC",
        "models": "era5",
    }
    for attempt in range(3):
        response = session.get(ENDPOINT, params=params, timeout=180)
        if response.status_code != 429 or attempt == 2:
            response.raise_for_status()
            break
        retry_after = response.headers.get("Retry-After")
        wait_seconds = int(retry_after) if retry_after and retry_after.isdigit() else 61
        print(f"ERA5 service rate limit; retrying after {wait_seconds} seconds")
        time.sleep(wait_seconds)
    payloads = response.json()
    if isinstance(payloads, dict):
        payloads = [payloads]
    if not isinstance(payloads, list) or len(payloads) != len(sites):
        raise RuntimeError("ERA5 response did not return one data block per Earth candidate")
    records = []
    for site, payload in zip(sites, payloads, strict=True):
        summary = era5.summarize_daily_response(payload)
        approximate_cell_scale_m = 27800 * math.sqrt(
            max(0.0, math.cos(math.radians(summary["grid_point"]["latitude_deg"])))
        )
        records.append(
            {
                "observation_id": f"{site['id']}:{era5.DATASET_ID}",
                "place_id": site["id"],
                "dataset_id": era5.DATASET_ID,
                "product_id": "ERA5 daily single-level reanalysis summaries",
                "provider": "ECMWF/Copernicus ERA5 via Open-Meteo Historical Weather API",
                "source_url": PROVIDER_URL,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "body": "earth",
                "candidate_latitude_deg": site["latitude_deg"],
                "candidate_longitude_east_deg": site["longitude_east_deg"],
                "latitude_deg": summary["grid_point"]["latitude_deg"],
                "longitude_east_deg": summary["grid_point"]["longitude_east_deg"],
                "location_precision": "nearest_era5_0.25_degree_grid_point",
                "grid_spacing_deg": summary["nominal_grid_spacing_deg"],
                "grid_elevation_m": summary["grid_elevation_m"],
                "grid_point_offset_km": _great_circle_km(
                    float(site["latitude_deg"]),
                    float(site["longitude_east_deg"]),
                    summary["grid_point"]["latitude_deg"],
                    summary["grid_point"]["longitude_east_deg"],
                ),
                "observation_period": (
                    f"{summary['returned_period']['start']} through "
                    f"{summary['returned_period']['end']}"
                ),
                "climate_normal_period": summary["requested_period"],
                "spatial_scale_m": approximate_cell_scale_m,
                "measurements": summary["measurements"],
                "mean_annual_precipitation_mm": summary["mean_annual_precipitation_mm"],
                "uncertainty": (
                    "ERA5 is a model reanalysis on an approximately 0.25° grid. The "
                    "requested location is snapped to the nearest grid point; this "
                    "is not a local weather-station record, and ENOM does not "
                    "estimate a full uncertainty range."
                ),
                "use_limit": (
                    "Climate context for Earth candidate places only. Temperature is "
                    "2 m air temperature, wind is 10 m wind, and precipitation is a "
                    "grid estimate; none is a direct surface-material, soil-water, "
                    "dust-event, or planetary-equivalent measurement. Not used for "
                    "analogue scores."
                ),
            }
        )
    payload = {
        "dataset_id": era5.DATASET_ID,
        "model": "ECMWF ERA5 reanalysis",
        "provider": "Open-Meteo Historical Weather API using ECMWF ERA5",
        "source_url": PROVIDER_URL,
        "baseline_period": {"start": era5.BASELINE_START, "end": era5.BASELINE_END},
        "retrieval_method": (
            "Daily point API response summarized into 30-year monthly "
            "climatologies; no gridded archive copied"
        ),
        "records": records,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"Wrote ERA5 context for {len(records)} Earth candidate places "
        f"to {OUTPUT.relative_to(ROOT)}"
    )


def _great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    import math

    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians((lon2 - lon1 + 180.0) % 360.0 - 180.0)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


if __name__ == "__main__":
    main()

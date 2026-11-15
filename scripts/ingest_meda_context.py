"""Ingest selected one-sol MEDA summaries from NASA PDS without keeping raw CSVs."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

from twinworld.meda import summarize_product, validate_sol_rows

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://pds-atmospheres.nmsu.edu/PDS/data/PDS4/Mars2020/mars2020_meda"
PDS_BUNDLE = "https://pds.nasa.gov/ds-view/pds/viewBundle.jsp?identifier=urn:nasa:pds:mars2020_meda&version=1.0"
HUMIDITY_METHOD = "https://doi.org/10.1016/j.pss.2022.105590"
OUTPUT = ROOT / "data/environment/mars2020-meda-sol100.json"
SOL = 100
MAX_PRODUCT_BYTES = 12_000_000

SENSORS = (
    {
        "sensor": "ATS",
        "collection": "data_calibrated_env",
        "product_code": "CAL_ATS",
        "dimension": "thermal_illumination",
        "column": "ATS_LOCAL_TEMP1",
        "name": "MEDA ATS local air temperature near mast sensor 1",
        "units": "K",
        "description": "Local air temperature measured near the Remote Sensing Mast at 50 degrees.",
        "use_limit": (
            "Calibrated one-sol rover measurement; not a seasonal climate "
            "statistic or illumination measure."
        ),
    },
    {
        "sensor": "WS",
        "collection": "data_derived_env",
        "product_code": "DER_WS",
        "dimension": "dust_processes",
        "column": "HORIZONTAL_WIND_SPEED",
        "uncertainty_column": "HORIZONTAL_WIND_SPEED_UNCERTAINTY",
        "name": "MEDA horizontal wind speed",
        "units": "m/s",
        "description": (
            "Derived horizontal wind speed; only rows with the rover stationary are summarized."
        ),
        "required_flags": {"ROVER_STILL": "1"},
        "use_limit": (
            "One sol of near-surface rover wind context; it does not measure "
            "dust movement or long-term wind climate."
        ),
    },
    {
        "sensor": "RHS",
        "collection": "data_derived_env",
        "product_code": "DER_RHS",
        "dimension": "water_resources",
        "column": "LOCAL_RELATIVE_HUMIDITY",
        "uncertainty_column": "LOCAL_RELATIVE_HUMIDITY_UNCERTAINTY",
        "name": "MEDA near-surface atmospheric relative humidity",
        "units": "%RH",
        "description": "Derived local atmospheric relative humidity, reported with respect to ice.",
        "use_limit": (
            "Sol 100 is after the sensor team's sol-80 recommendation. "
            "Self-heating can affect continuous-mode readings; this is "
            "atmospheric water vapour context, not soil water, ice, or a "
            "usable resource."
        ),
    },
)


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def _sol_bucket(sol: int) -> str:
    if 0 <= sol <= 89:
        return "sol_0000_0089"
    if 90 <= sol <= 179:
        return "sol_0090_0179"
    if sol < 0:
        raise ValueError("Sol number must be non-negative")
    start = 180 + ((sol - 180) // 120) * 120
    return f"sol_{start:04d}_{start + 119:04d}"


def _fetch(url: str, *, max_bytes: int = MAX_PRODUCT_BYTES) -> bytes:
    result = subprocess.run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--max-time",
            "180",
            "--max-filesize",
            str(max_bytes),
            url,
        ],
        check=True,
        capture_output=True,
    )
    data = result.stdout
    if len(data) > max_bytes:
        raise ValueError(f"PDS product exceeds the {max_bytes:,}-byte limit: {url}")
    return data


def _product_url(sol: int, sensor: dict[str, object]) -> str:
    collection = str(sensor["collection"])
    product_code = str(sensor["product_code"])
    folder = f"{BASE}/{collection}/{_sol_bucket(sol)}/sol_{sol:04d}/"
    listing = _fetch(folder, max_bytes=2_000_000).decode("utf-8", errors="replace")
    parser = _Links()
    parser.feed(listing)
    pattern = re.compile(
        rf"^WE__{sol:04d}.*{re.escape(product_code)}.*P(\d+)\.CSV$",
        re.IGNORECASE,
    )
    products = []
    for href in parser.hrefs:
        match = pattern.match(href)
        if match:
            products.append((int(match.group(1)), href))
    if not products:
        raise FileNotFoundError(f"No PDS {product_code} CSV is indexed for sol {sol}")
    _, filename = max(products)
    return folder + filename


def _time_range(csv_text: str) -> tuple[str | None, str | None]:
    import csv
    import io

    rows = csv.DictReader(io.StringIO(csv_text))
    times = [row.get("LMST", "") for row in rows]
    times = [value for value in times if value]
    return (times[0], times[-1]) if times else (None, None)


def main() -> None:
    records = []
    retrieved_at = datetime.now(UTC).isoformat()
    for sensor in SENSORS:
        product_url = _product_url(SOL, sensor)
        print(f"Summarizing MEDA {sensor['sensor']} from PDS sol {SOL}", flush=True)
        csv_text = _fetch(product_url).decode("ascii")
        source_row_count = validate_sol_rows(csv_text, SOL)
        measurement = summarize_product(
            csv_text,
            sensor=str(sensor["sensor"]),
            value_column=str(sensor["column"]),
            value_name=str(sensor["name"]),
            units=str(sensor["units"]),
            uncertainty_column=(
                str(sensor["uncertainty_column"]) if sensor.get("uncertainty_column") else None
            ),
            uncertainty_units=str(sensor["units"]),
            required_flags=sensor.get("required_flags"),  # type: ignore[arg-type]
        )
        humidity_uncertainty = measurement["uncertainty"].get("value")
        if (
            sensor["sensor"] == "RHS"
            and isinstance(humidity_uncertainty, (int, float))
            and measurement["value"] <= humidity_uncertainty
        ):
            sensor_use_limit = (
                str(sensor["use_limit"])
                + f" The sol median ({measurement['value']:.2f} %RH) is no greater than the "
                + f"median of the reported per-row uncertainties ({humidity_uncertainty:.2f} %RH)."
            )
        else:
            sensor_use_limit = str(sensor["use_limit"])
        first_time, last_time = _time_range(csv_text)
        record_id = f"mars2020-meda-sol-{SOL:04d}-{str(sensor['sensor']).lower()}"
        records.append(
            {
                "observation_id": record_id,
                "place_id": "mars-jezero",
                "body": "mars",
                "name": f"Perseverance MEDA {sensor['sensor']} · Mars sol {SOL}",
                "dataset_id": "mars2020-meda",
                "product_id": product_url.rsplit("/", 1)[-1],
                "provider": "NASA Planetary Data System Atmospheres Node",
                "source_url": product_url,
                "dataset_reference_url": PDS_BUNDLE,
                "units_reference_url": HUMIDITY_METHOD if sensor["sensor"] == "RHS" else None,
                "acquired_at": f"Mars sol {SOL}; LMST {first_time} to {last_time}",
                "kind": "measurement",
                "dimensions": [str(sensor["dimension"])],
                "latitude_deg": 18.44,
                "longitude_east_deg": 77.45,
                "location_precision": "rover_track_in_mission_region",
                "spatial_relation": (
                    "Perseverance rover observation within the Jezero mission "
                    "region; catalogue coordinates mark a regional locator, not the "
                    "rover's exact position for every sample."
                ),
                "summary": str(sensor["description"]),
                "use_limit": sensor_use_limit,
                "evidence_kind": "measured" if sensor["sensor"] == "ATS" else "derived",
                "quality_note": (
                    "PDS fill values and non-finite samples are excluded. "
                    f"{measurement['quality_filtered_row_count']} rows were excluded "
                    "by the sensor quality filter. This one-sol summary is displayed "
                    "as context only and is not used for analogue scoring."
                ),
                "temporal_coverage": {
                    "martian_sol": SOL,
                    "local_mean_solar_time_start": first_time,
                    "local_mean_solar_time_stop": last_time,
                },
                "row_count": source_row_count,
                "measurements": [measurement],
                "retrieved_at": retrieved_at,
                "processing_method": (
                    "One-sol median and p10–p90 summary from the current PDS "
                    "derived/calibrated CSV product; raw CSV is not retained."
                ),
            }
        )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "dataset_id": "mars2020-meda",
                "bundle_url": PDS_BUNDLE,
                "records": records,
                "retrieved_at": retrieved_at,
                "scope": (
                    "Selected Mars sol 100 only; not a Mars climate normal or full "
                    "rover traverse archive."
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Saved {len(records)} MEDA sol-{SOL} summaries to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Fetch compact NASA POWER point climatologies for Earth catalogue places.

This stores a few monthly/annual summary values per Earth candidate, not raster
datasets. Values are contextual reanalysis/model products and are not analogue scores.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = ROOT / "data/manifests/candidate-locations.json"
OUTPUT = ROOT / "data/environment/nasa-power-climatology.json"
ENDPOINT = "https://power.larc.nasa.gov/api/temporal/climatology/point"
PARAMETERS = ("T2M", "RH2M", "WS10M", "ALLSKY_SFC_SW_DWN")


def _fetch(latitude: float, longitude: float) -> dict[str, object]:
    query = urlencode(
        {
            "parameters": ",".join(PARAMETERS),
            "community": "RE",
            "longitude": longitude,
            "latitude": latitude,
            "format": "JSON",
        }
    )
    request = Request(ENDPOINT + "?" + query, headers={"User-Agent": "ENOM-science-prototype/1.0"})
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
                returned = payload.get("properties", {}).get("parameter", {})
                if not isinstance(returned, dict) or any(
                    parameter not in returned for parameter in PARAMETERS
                ):
                    raise RuntimeError("NASA POWER response is missing requested parameter data")
                return payload
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
    raise RuntimeError(f"NASA POWER request failed: {last_error}") from last_error


def main() -> None:
    catalogue = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    sites = [entry for entry in catalogue["entries"] if entry["body"] == "earth"]
    retrieved_at = datetime.now(UTC).isoformat()
    records = []
    for index, site in enumerate(sites):
        longitude = float(site["longitude_east_deg"])
        if longitude > 180:
            longitude -= 360
        payload = _fetch(float(site["latitude_deg"]), longitude)
        parameters = payload.get("properties", {}).get("parameter", {})
        definitions = payload.get("parameters", {})
        fill = payload.get("header", {}).get("fill_value", -999.0)
        measurements = []
        for parameter in PARAMETERS:
            values = parameters.get(parameter, {})
            definition = definitions.get(parameter, {})
            raw_annual = values.get("ANN")
            annual = None if raw_annual is None or raw_annual == fill else float(raw_annual)
            monthly = {
                month: (None if value is None or value == fill else float(value))
                for month, value in values.items()
                if month != "ANN"
            }
            measurements.append(
                {
                    "name": parameter,
                    "label": definition.get("longname", parameter),
                    "value": annual,
                    "units": definition.get("units", "unknown"),
                    "availability": "available" if annual is not None else "not_observed",
                    "monthly_values": monthly,
                    "temporal_coverage": payload.get("header", {}).get("range"),
                    "uncertainty": (
                        "Gridded climatology/reanalysis estimate; not an in-situ site measurement."
                    ),
                }
            )
        records.append(
            {
                "place_id": site["id"],
                "body": "earth",
                "name": site["name"],
                "latitude_deg": site["latitude_deg"],
                "longitude_east_deg": site["longitude_east_deg"],
                "dataset_id": "nasa-power-climatology",
                "provider": "NASA Langley Research Center POWER project",
                "source_product_id": "POWER Climatology API; " + ", ".join(PARAMETERS),
                "source_url": ENDPOINT
                + "?"
                + urlencode(
                    {
                        "parameters": ",".join(PARAMETERS),
                        "community": "RE",
                        "longitude": longitude,
                        "latitude": site["latitude_deg"],
                        "format": "JSON",
                    }
                ),
                "dataset_reference_url": "https://power.larc.nasa.gov/docs/services/api/temporal/climatology/",
                "retrieved_at": retrieved_at,
                "period": payload.get("header", {}).get("range"),
                "api_version": payload.get("header", {}).get("api", {}).get("version"),
                "gridded_elevation_m": (
                    payload.get("geometry", {}).get("coordinates") or [None, None, None]
                )[2],
                "native_sources": payload.get("header", {}).get("sources", []),
                "measurements": measurements,
                "processing_method": (
                    "Annual climatology value returned by NASA POWER; monthly values "
                    "retained without re-averaging."
                ),
            }
        )
        if index + 1 < len(sites):
            time.sleep(0.2)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {"retrieved_at": retrieved_at, "source": "NASA POWER", "records": records}, indent=2
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(records)} small site climatology records to {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

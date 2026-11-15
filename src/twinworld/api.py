"""FastAPI service over the checked-in pilot catalogue and remote-produced embeddings."""

from __future__ import annotations

import io
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import numpy as np
import rasterio
import yaml  # type: ignore[import-untyped]
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from PIL import Image, ImageDraw
from pydantic import BaseModel, Field, field_validator

from twinworld import analogue, offline_imagery
from twinworld.records import PatchRecord, read_jsonl
from twinworld.retrieval import search as visual_search
from twinworld.science import Availability, EvidenceRecord, PhysicalMeasurement
from twinworld.scorecards import (
    MISSION_PRESETS,
    VARIABLES,
    compare_candidate,
    mission_suitability,
    validate_weights,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "data/manifests/pilot-100.jsonl"
CATALOGUE = ROOT / "data/manifests/candidate-locations.json"
MODEL_CONFIG = ROOT / "configs/models.yaml"
EMBEDDINGS = Path(
    os.getenv("TWINWORLD_EMBEDDINGS", str(ROOT / "artifacts/pilot-100/embeddings_dinov2.npy"))
)
TERRAIN_SIDECARS = tuple(sorted((ROOT / "data/terrain").glob("*.tif.json")))
MIN_TERRAIN_COVERAGE = float(os.getenv("TWINWORLD_MIN_TERRAIN_COVERAGE", "0.25"))
if not 0.0 <= MIN_TERRAIN_COVERAGE <= 1.0:
    raise ValueError("TWINWORLD_MIN_TERRAIN_COVERAGE must be between 0 and 1")


@lru_cache(maxsize=8)
def _metadata_for_dataset(dataset_id: str) -> list[dict[str, object]]:
    results = []
    for path in TERRAIN_SIDECARS:
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if metadata.get("dataset_id") == dataset_id:
            results.append(metadata)
    return results


@lru_cache(maxsize=1)
def _nasa_power_records() -> list[dict[str, Any]]:
    path = ROOT / "data/environment/nasa-power-climatology.json"
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("records", [])
    return rows if isinstance(rows, list) else []


def _nasa_power_version() -> str:
    rows = _nasa_power_records()
    return (
        str(rows[0].get("api_version", "POWER Climatology API"))
        if rows
        else "POWER Climatology API"
    )


@lru_cache(maxsize=1)
def _meda_records() -> list[dict[str, Any]]:
    path = ROOT / "data/environment/mars2020-meda-sol100.json"
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("records", [])
    return rows if isinstance(rows, list) else []


class SearchRequest(BaseModel):
    """Options for searching from one observation in the indexed pilot."""

    observation_id: str
    profile: Literal["aeolian", "rover_mobility", "ancient_water", "volcanic"] = "aeolian"
    method: Literal["visual", "terrain", "combined"] = "visual"
    limit: int = Field(default=10, ge=1, le=50)


class SearchResult(BaseModel):
    """One ranked cross-body candidate and its visual/terrain evidence."""

    observation_id: str
    rank: int
    cosine_similarity: float
    terrain_similarity: float | None = None
    combined_score: float | None = None
    visual_rank: int | None = None
    rank_change_from_visual: int | None = None
    eligible_visual_rank: int | None = None
    rank_change_within_eligible: int | None = None
    ranking_evidence: list[str] = []
    terrain_quality: dict[str, object] | None = None
    retrieval_method: str
    source_url: str
    location: dict[str, str | float | None]
    image_url: str
    evidence: list[EvidenceRecord]


class SearchResponse(BaseModel):
    """Search scope, ranked candidates, evidence counts, and limitations."""

    query_observation_id: str
    profile: str
    method: str
    results: list[SearchResult]
    scope: str
    terrain_eligible_candidates: int
    terrain_excluded_candidates: int
    query_terrain_quality: dict[str, object]
    limitations: list[str]


class ScorecardRequest(BaseModel):
    """Reference site and terrain-variable weights for a scorecard ranking."""

    site_id: str
    mission_objective: Literal["landing", "base_construction", "rover_mobility"]
    weights: dict[str, float]
    limit: int = Field(default=20, ge=1, le=100)


class AnalogueDiscoveryRequest(BaseModel):
    """Rank unique Earth places against one indexed ENOM target place."""

    target_site_id: str
    profile_id: str
    weights: dict[str, float] | None = None
    limit: int = Field(default=10, ge=1, le=10)

    @field_validator("weights", mode="before")
    @classmethod
    def weights_must_be_numeric(cls, value: object) -> object:
        if value is None:
            return value
        if not isinstance(value, dict) or any(
            isinstance(weight, bool) or not isinstance(weight, (int, float))
            for weight in value.values()
        ):
            raise ValueError("Every dimension weight must be a number")
        return value


@lru_cache(maxsize=1)
def _load() -> tuple[list[PatchRecord], dict[str, int], np.ndarray]:
    if not MANIFEST.is_file() or not EMBEDDINGS.is_file():
        return [], {}, np.empty((0, 0), dtype=np.float32)
    records = read_jsonl(MANIFEST)
    matrix = np.load(EMBEDDINGS, allow_pickle=False)
    metadata_path = EMBEDDINGS.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    _validate_embedding_identity(metadata)
    if metadata.get("image_ids") != [record.image_id for record in records]:
        raise RuntimeError("DINOv2 embedding IDs do not match the manifest order")
    if matrix.ndim != 2 or matrix.shape[0] != len(records):
        raise RuntimeError("DINOv2 embedding matrix does not match the manifest")
    if matrix.shape[1] != metadata.get("embedding_dimension"):
        raise RuntimeError("DINOv2 embedding dimension does not match artifact metadata")
    if not np.isfinite(matrix).all():
        raise RuntimeError("DINOv2 embedding matrix contains non-finite values")
    return records, {record.image_id: index for index, record in enumerate(records)}, matrix


def _validate_embedding_identity(metadata: dict[str, Any]) -> None:
    """Require embedding metadata to match a configured model and preprocessing."""
    config = yaml.safe_load(MODEL_CONFIG.read_text(encoding="utf-8"))
    preprocessing_id = config["preprocessing"]["id"]
    matching_models = [
        profile
        for profile in config["models"].values()
        if metadata.get("model_id") == profile["model_id"]
        and metadata.get("revision") == profile["revision"]
        and metadata.get("embedding_dimension") == profile["embedding_dimension"]
    ]
    if not matching_models:
        raise RuntimeError("DINOv2 embedding model identity is not configured")
    if metadata.get("preprocessing_id") != preprocessing_id:
        raise RuntimeError("DINOv2 embedding preprocessing does not match the model config")
    expected_space_id = f"{metadata['model_id']}@{metadata['revision']}:{preprocessing_id}"
    if metadata.get("embedding_space_id", expected_space_id) != expected_space_id:
        raise RuntimeError("DINOv2 embedding-space identity is inconsistent")


def _record_payload(record: PatchRecord) -> dict[str, object]:
    measurements = _terrain_measurements(record.image_id)
    available_measurements = _available_terrain_measurements(record.image_id)
    terrain_records = _terrain_records(record.image_id)
    geology = _geology_evidence_for(record.image_id)
    geology_is_mapped = geology is not None and geology.get("classification_status") == "mapped"
    return {
        "id": record.image_id,
        "body": record.body,
        "longitude_east_deg": (
            record.longitude % 360.0 if record.body == "mars" else record.longitude
        ),
        "latitude_deg": record.latitude,
        "width_m": record.width_m,
        "height_m": record.height_m,
        "native_resolution_m": record.native_gsd_m,
        "crs": record.crs,
        "source_id": record.source_id,
        "source_url": record.source_url,
        "provider": record.provider,
        "acquired_at": record.acquired_at,
        "label": record.label,
        "label_status": record.label_status,
        "geographic_group": record.geographic_group,
        "image_url": f"/api/observations/{record.image_id}/image",
        "available_evidence": ["surface_imagery", "visual_embedding"]
        + (["terrain_dem"] if available_measurements else [])
        + (["geology"] if geology_is_mapped else []),
        "unavailable_evidence": [
            name
            for name in ("terrain_dem", "geology", "mineralogy", "thermal")
            if not (
                (name == "terrain_dem" and available_measurements)
                or (name == "geology" and geology_is_mapped)
            )
        ],
        "measurements": [item.model_dump(mode="json") for item in measurements],
        "terrain_contexts": [
            {
                key: metadata[key]
                for key in (
                    "dataset_id",
                    "provider",
                    "source_product_id",
                    "source_url",
                    "context_size_m",
                    "observed_cell_count",
                    "grid_cell_count",
                    "observed_cell_fraction",
                    "valid_pixel_count",
                    "valid_pixel_fraction",
                    "native_resolution_m_at_equator",
                    "output_pixel_size_m",
                    "processing_method",
                    "missing_data_semantics",
                    "observation_period",
                    "dataset_version",
                )
                if key in metadata
            }
            for metadata in terrain_records
        ],
    }


def _terrain_measurements(observation_id: str) -> list[PhysicalMeasurement]:
    measurements: list[PhysicalMeasurement] = []
    for metadata in _terrain_records(observation_id):
        raw_measurements = metadata.get("measurements", [])
        if isinstance(raw_measurements, list):
            measurements.extend(
                PhysicalMeasurement.model_validate(item) for item in raw_measurements
            )
    return measurements


def _available_terrain_measurements(observation_id: str) -> list[PhysicalMeasurement]:
    """Return valued terrain measurements whose availability is explicitly known."""
    return [
        measurement
        for measurement in _terrain_measurements(observation_id)
        if measurement.availability is Availability.AVAILABLE and measurement.value is not None
    ]


@lru_cache(maxsize=256)
def _terrain_records(observation_id: str) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for sidecar in TERRAIN_SIDECARS:
        if not sidecar.is_file():
            continue
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        if metadata.get("observation_id") == observation_id:
            found.append(metadata)
    return found


def _terrain_quality(observation_id: str) -> dict[str, object]:
    metadata = _terrain_records(observation_id)
    if not metadata:
        return {"eligible": False, "coverage": 0.0, "reason": "No DEM observation is indexed."}
    coverage_values = []
    for item in metadata:
        raw_coverage = item.get("observed_cell_fraction", item.get("valid_pixel_fraction", 1.0))
        coverage_values.append(
            float(raw_coverage) if isinstance(raw_coverage, (int, float)) else 0.0
        )
    coverage = max(coverage_values, default=0.0)
    if coverage < MIN_TERRAIN_COVERAGE:
        return {
            "eligible": False,
            "coverage": coverage,
            "minimum_coverage": MIN_TERRAIN_COVERAGE,
            "reason": "Observed-cell coverage is below the configured terrain threshold.",
        }
    return {
        "eligible": True,
        "coverage": coverage,
        "minimum_coverage": MIN_TERRAIN_COVERAGE,
        "sources": [item.get("source_product_id") for item in metadata],
    }


@lru_cache(maxsize=256)
def _terrain_vector(observation_id: str) -> dict[str, tuple[float, float, str]]:
    vector: dict[str, tuple[float, float, str]] = {}
    if not _terrain_quality(observation_id)["eligible"]:
        return vector
    for measurement in _available_terrain_measurements(observation_id):
        if measurement.value is not None and measurement.spatial_scale_m is not None:
            vector[measurement.name] = (
                float(measurement.value),
                float(measurement.spatial_scale_m),
                measurement.units,
            )
    return vector


def _terrain_similarity(query_id: str, candidate_id: str, all_ids: list[str]) -> float | None:
    vectors = {observation_id: _terrain_vector(observation_id) for observation_id in all_ids}
    query, candidate = vectors[query_id], vectors[candidate_id]
    common = sorted(set(query) & set(candidate))
    if not common:
        return None
    distances = []
    for name in common:
        q_value, q_scale, q_units = query[name]
        c_value, c_scale, c_units = candidate[name]
        if q_units != c_units or max(q_scale, c_scale) / min(q_scale, c_scale) > 1.05:
            continue
        values = [vector[name][0] for vector in vectors.values() if name in vector]
        median = float(np.median(values))
        mad = float(np.median(np.abs(np.asarray(values) - median)))
        scale = 1.4826 * mad
        if scale <= 1e-9:
            scale = max(float(np.std(values)), 1.0)
        distances.append(abs(q_value - c_value) / scale)
    return float(np.exp(-np.mean(distances))) if distances else None


def _terrain_summary(observation_id: str) -> str:
    records = _terrain_records(observation_id)
    if not records:
        return "No terrain elevation observation is indexed for this region."
    summaries = []
    for metadata in records:
        if metadata.get("dataset_id") == "mola-meg128":
            fraction = metadata.get("observed_cell_fraction", 0.0)
            count = metadata.get("observed_cell_count", 0)
            total = metadata.get("grid_cell_count", 0)
            summaries.append(
                f"MOLA MEG128 elevation over a {metadata['context_size_m']:.0f} m context; "
                f"altimetry exists in {count}/{total} bins ({fraction:.1%}); "
                "empty-bin interpolations are excluded."
            )
        else:
            summaries.append(
                f"Copernicus DEM GLO-30 digital surface model over a "
                f"{metadata['context_size_m']:.0f} m context, resampled to match MOLA posting."
            )
    return " ".join(summaries)


app = FastAPI(title="TwinWorld research API", version="0.4.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, object]:
    """Report API readiness and whether the local visual index is available."""
    records, _, matrix = _load()
    return {"status": "ok", "records": len(records), "visual_index": bool(matrix.size)}


@app.get("/api/imagery/offline/status")
def offline_globe_map_status() -> dict[str, object]:
    return offline_imagery.status()


@app.post("/api/imagery/offline/start")
def start_offline_globe_maps() -> dict[str, object]:
    return offline_imagery.start()


@app.post("/api/imagery/offline/pause")
def pause_offline_globe_maps() -> dict[str, object]:
    return offline_imagery.pause()


@app.post("/api/imagery/offline/cancel")
def cancel_offline_globe_maps() -> dict[str, object]:
    return offline_imagery.cancel()


@app.delete("/api/imagery/offline")
def clear_offline_globe_maps() -> dict[str, object]:
    try:
        return offline_imagery.clear()
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.get("/api/imagery/offline/tiles/{body}/{version}/{matrix_set}/{matrix_id}/{row}/{col}")
def get_offline_globe_tile(
    body: str, version: str, matrix_set: str, matrix_id: str, row: int, col: int
) -> Response:
    if offline_imagery.tile_is_missing(body, version, matrix_set, matrix_id, row, col):
        raise HTTPException(status_code=410, detail="NASA confirmed that this tile is unavailable")
    path = offline_imagery.tile_file(body, version, matrix_set, matrix_id, row, col)
    if path is None:
        raise HTTPException(status_code=404, detail="Tile is not saved in the repository")
    media_type = "image/jpeg"
    return Response(
        path.read_bytes(),
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@app.put("/api/imagery/offline/tiles/{body}/{version}/{matrix_set}/{matrix_id}/{row}/{col}")
async def save_viewed_globe_tile(
    body: str, version: str, matrix_set: str, matrix_id: str, row: int, col: int, request: Request
) -> dict[str, object]:
    saved = offline_imagery.save_viewed_tile(
        body, version, matrix_set, matrix_id, row, col, await request.body()
    )
    if not saved:
        raise HTTPException(status_code=400, detail="Invalid globe tile or imagery source version")
    return {"saved": True}


@app.get("/api/planets")
def planets() -> list[dict[str, object]]:
    """List bodies and their indexed observation counts."""
    records = read_jsonl(MANIFEST) if MANIFEST.is_file() else []
    bodies = {record.body for record in records}
    return [
        {
            "id": body,
            "available": body in bodies,
            "indexed_observations": sum(r.body == body for r in records),
        }
        for body in ("earth", "mars", "moon")
    ]


@app.get("/api/catalogue")
def catalogue() -> dict[str, object]:
    """Return candidate regions independently of imagery or raster availability."""
    if not CATALOGUE.is_file():
        return {"catalogue_id": "planetary-targets-and-analogue-candidates-v1", "entries": []}
    return json.loads(CATALOGUE.read_text(encoding="utf-8"))


@app.get("/api/places")
def places() -> dict[str, object]:
    """List unique places with their linked source observations and coverage."""
    rows = analogue.build_places(ROOT)
    return {
        "places": [
            {
                **{key: value for key, value in place.items() if key != "observations"},
                "observations": [
                    {
                        key: value
                        for key, value in item.items()
                        if key not in {"metadata", "measurements", "local_path"}
                    }
                    for item in place["observations"]
                ],
                "evidence": analogue._dimension_evidence(place),
            }
            for place in rows
        ],
        "scope": "Current candidate catalogue and reviewed, source-backed observation contexts.",
    }


def _render_place_layer(
    place_id: str, layer_type: Literal["elevation", "slope", "roughness", "coverage", "thermal"]
) -> Response:
    place_rows = analogue.build_places(ROOT)
    place = next(
        (
            row
            for row in place_rows
            if row["id"] == place_id or any(item["id"] == place_id for item in row["observations"])
        ),
        None,
    )
    if place is None:
        raise HTTPException(404, detail="Place is not indexed")
    raster_path = None
    coverage_is_count = False
    terrain_datasets = {
        "cop-dem-glo-30",
        "nasadem-hgt",
        "mola-meg128",
        "lro-lola-gdr-ldem-64",
        "lro-lola-gdr-polar-ldem-120m",
    }
    thermal_datasets = {"lro-diviner-gdr-level3-st-clc", "mgs-tes-derived-thermal-inertia"}
    eligible_datasets = thermal_datasets if layer_type == "thermal" else terrain_datasets
    for item in place["observations"]:
        if item.get("dataset_id") not in eligible_datasets:
            continue
        metadata = item.get("metadata", {})
        if layer_type == "coverage":
            if metadata.get("count_raster") and (ROOT / str(metadata["count_raster"])).is_file():
                candidate_path = metadata["count_raster"]
                coverage_is_count = True
            elif item.get("dataset_id") == "cop-dem-glo-30":
                candidate_path = metadata.get("output") or metadata.get("terrain_raster")
                coverage_is_count = False
            else:
                continue
        else:
            candidate_path = metadata.get("output") or metadata.get("terrain_raster")
        if candidate_path and (ROOT / str(candidate_path)).is_file():
            raster_path = ROOT / str(candidate_path)
            break
    if raster_path is None:
        raise HTTPException(404, detail="No local elevation raster is available for this place")
    with rasterio.open(raster_path) as dataset:
        values = dataset.read(1, masked=True).astype(np.float32).filled(np.nan)
        if layer_type == "coverage":
            values = np.where(np.isfinite(values), values, np.nan)
            if coverage_is_count:
                values[values <= 0] = np.nan
        elif layer_type == "slope":
            valid_source = np.isfinite(values)
            if not valid_source.any():
                raise HTTPException(422, detail="Elevation layer has no valid cells")
            filled = np.where(valid_source, values, float(np.nanmedian(values[valid_source])))
            dx = float(np.hypot(dataset.transform.a, dataset.transform.d))
            dy = float(np.hypot(dataset.transform.b, dataset.transform.e))
            gy, gx = np.gradient(filled, dy, dx)
            values = np.degrees(np.arctan(np.hypot(gx, gy))).astype(np.float32)
            valid_source[[0, -1], :] = False
            valid_source[:, [0, -1]] = False
            values[~valid_source] = np.nan
        elif layer_type == "roughness":
            valid_source = np.isfinite(values)
            if valid_source.sum() < 9:
                raise HTTPException(422, detail="Elevation layer has fewer than nine valid cells")
            from scipy.ndimage import minimum_filter, uniform_filter

            filled = np.where(valid_source, values, float(np.nanmedian(values[valid_source])))
            neighborhood_complete = (
                minimum_filter(valid_source.astype(np.uint8), size=3, mode="constant", cval=0) == 1
            )
            neighborhood_complete[[0, -1], :] = False
            neighborhood_complete[:, [0, -1]] = False
            values = np.abs(filled - uniform_filter(filled, size=3, mode="nearest"))
            values[~neighborhood_complete] = np.nan
            if not np.isfinite(values).any():
                raise HTTPException(422, detail="Elevation layer has no complete 3×3 neighborhoods")
    valid = np.isfinite(values)
    if not valid.any():
        raise HTTPException(422, detail="Elevation layer has no valid cells")
    if layer_type == "slope":
        low, high = 0.0, 30.0
    else:
        low, high = np.nanpercentile(values[valid], [2, 98])
    scale = max(float(high - low), 1e-9)
    normalized = np.clip((values - low) / scale, 0, 1)
    normalized = np.where(valid, normalized, 0.0)
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    rgba[:, :, 0] = (35 + normalized * 210).astype(np.uint8)
    rgba[:, :, 1] = (72 + normalized * 150).astype(np.uint8)
    rgba[:, :, 2] = (125 - normalized * 80).astype(np.uint8)
    rgba[:, :, 3] = np.where(valid, 255, 0).astype(np.uint8)
    image = Image.fromarray(rgba).resize((256, 256), Image.Resampling.NEAREST)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/api/places/{place_id}/layers/elevation.png")
def place_elevation_preview(place_id: str) -> Response:
    """Render a small local elevation preview in the source raster's map orientation."""
    return _render_place_layer(place_id, "elevation")


@app.get("/api/places/{place_id}/layers/slope.png")
def place_slope_preview(place_id: str) -> Response:
    """Render an on-demand slope layer derived from the local DEM."""
    return _render_place_layer(place_id, "slope")


@app.get("/api/places/{place_id}/layers/roughness.png")
def place_roughness_preview(place_id: str) -> Response:
    """Render median-deviation-from-3x3-mean roughness from a local DEM."""
    return _render_place_layer(place_id, "roughness")


@app.get("/api/places/{place_id}/layers/coverage.png")
def place_coverage_preview(place_id: str) -> Response:
    """Render observed MOLA count support or Copernicus valid-cell coverage."""
    return _render_place_layer(place_id, "coverage")


@app.get("/api/places/{place_id}/layers/thermal.png")
def place_thermal_preview(place_id: str) -> Response:
    """Render a local Diviner temperature or TES thermal-inertia context raster."""
    return _render_place_layer(place_id, "thermal")


@app.get("/api/places/{place_id}/layers/mini-rf-cpr.png")
def place_minirf_cpr_preview(place_id: str) -> Response:
    """Render a bounded Mini-RF CPR sample using a fixed 0–1.5 ratio scale."""
    place = next((row for row in analogue.build_places(ROOT) if row["id"] == place_id), None)
    if place is None:
        raise HTTPException(404, detail="Place is not indexed")
    observation = next(
        (
            item
            for item in place["observations"]
            if item.get("dataset_id") == "lro-mini-rf-south-polar-cpr"
            and item.get("metadata", {}).get("grid_values")
        ),
        None,
    )
    if observation is None:
        raise HTTPException(404, detail="No Mini-RF CPR sample is available for this place")
    values = np.asarray(observation["metadata"]["grid_values"], dtype=np.float32)
    valid = np.isfinite(values)
    normalized = np.clip(values / 1.5, 0.0, 1.0)
    rgba = np.zeros((*values.shape, 4), dtype=np.uint8)
    rgba[:, :, 0] = (30 + normalized * 220).astype(np.uint8)
    rgba[:, :, 1] = (45 + normalized * 170).astype(np.uint8)
    rgba[:, :, 2] = (110 - normalized * 80).astype(np.uint8)
    rgba[:, :, 3] = np.where(valid, 255, 0).astype(np.uint8)
    image = Image.fromarray(rgba).resize((256, 256), Image.Resampling.NEAREST)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/api/places/{place_id}/layers/rover-operations.png")
def place_rover_operations_preview(place_id: str) -> Response:
    """Render discrete Jezero rover position fixes on their local Mars DEM grid."""
    place = next((row for row in analogue.build_places(ROOT) if row["id"] == place_id), None)
    if place is None:
        raise HTTPException(404, detail="Place is not indexed")
    observation = next(
        (
            item
            for item in place["observations"]
            if item.get("dataset_id") == "mars2020-rover-places-best-tactical"
        ),
        None,
    )
    if observation is None:
        raise HTTPException(
            404, detail="No Perseverance drive-position records are available for this place"
        )
    terrain = next(
        (
            item
            for item in place["observations"]
            if item.get("dataset_id") == "mola-meg128"
            and (
                item.get("metadata", {}).get("output")
                or item.get("metadata", {}).get("terrain_raster")
            )
        ),
        None,
    )
    if terrain is None:
        raise HTTPException(404, detail="No local Mars DEM is available to align rover positions")
    metadata = terrain.get("metadata", {})
    raster_path = metadata.get("output") or metadata.get("terrain_raster")
    if not raster_path or not (ROOT / str(raster_path)).is_file():
        raise HTTPException(404, detail="The indexed Mars DEM raster is not present")
    waypoints = observation.get("metadata", {}).get("records", [])
    with rasterio.open(ROOT / str(raster_path)) as dataset:
        if dataset.width <= 0 or dataset.height <= 0:
            raise HTTPException(422, detail="Mars DEM raster has no displayable cells")
        render_size = 512
        overlay = Image.new("RGBA", (render_size, render_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        plotted = 0
        for point in waypoints:
            latitude = float(point["latitude_deg"])
            longitude = float(point["longitude_east_deg"])
            # MOLA Jezero crops use simple equirectangular Mars coordinates,
            # central meridian 180°, and a 3,396 km reference sphere.
            x = 3_396_000.0 * np.deg2rad(longitude - 180.0)
            y = 3_396_000.0 * np.deg2rad(latitude)
            column, row = (~dataset.transform) @ (float(x), float(y))
            if 0.0 <= row < dataset.height and 0.0 <= column < dataset.width:
                render_column = column * render_size / dataset.width
                render_row = row * render_size / dataset.height
                draw.ellipse(
                    (render_column - 2, render_row - 2, render_column + 2, render_row + 2),
                    fill=(255, 211, 79, 255),
                )
                plotted += 1
        if not plotted:
            raise HTTPException(
                404, detail="No rover position falls inside the local DEM map window"
            )
        image = overlay.resize((256, 256), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return Response(
        content=buffer.getvalue(),
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=300",
            "X-ENOM-Displayed-Positions": str(plotted),
            "X-ENOM-Total-Positions": str(len(waypoints)),
        },
    )


@app.get("/api/analogue/profiles")
def analogue_profiles() -> list[dict[str, object]]:
    return [
        {
            "id": profile_id,
            "name": profile["name"],
            "description": profile["description"],
            "weights": profile["weights"],
            "dimensions": analogue.DIMENSIONS,
        }
        for profile_id, profile in analogue.PROFILES.items()
    ]


@app.get("/api/analogue/sources")
def analogue_sources() -> list[dict[str, object]]:
    """List source integrations with current local coverage and connection status."""
    return analogue.source_inventory(ROOT)


@app.post("/api/analogue/discover")
def discover_analogues(request: AnalogueDiscoveryRequest) -> dict[str, object]:
    """Return evidence-aware rankings for at most ten distinct Earth places."""
    try:
        return analogue.discover(
            ROOT, request.target_site_id, request.profile_id, request.weights, request.limit
        )
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(
            404,
            detail={
                "code": "target_place_not_found",
                "message": f"No indexed place has ID '{request.target_site_id}'",
            },
        ) from exc


@app.get("/api/datasets")
def datasets() -> list[dict[str, object]]:
    return [
        {
            "id": "pilot-surface-imagery",
            "provider": "ESA Sentinel-2 / MRO CTX and source products described in the manifest",
            "name": "ENOM Phase 0 pilot imagery and DINOv2 embeddings",
            "version": "pilot-100; checkpoint revision recorded in artifact metadata",
            "bodies": ["earth", "mars"],
            "variable": "surface imagery / visual embedding",
            "units": (
                "Embedding coordinates are dimensionless; cosine similarity is a retrieval metric"
            ),
            "native_resolution_m": "per-observation",
            "access_method": "local manifest and precomputed NumPy index",
            "status": "operational",
            "source_url": "per-observation source_url in the manifest",
        },
        {
            "id": "cop-dem-glo-30",
            "provider": "Copernicus / Microsoft Planetary Computer",
            "name": "Copernicus DEM GLO-30",
            "version": "GLO-30; tile identity recorded per observation",
            "bodies": ["earth"],
            "variable": "digital surface elevation",
            "units": "m",
            "native_resolution_m": 30,
            "access_method": "Planetary Computer STAC / Cloud Optimized GeoTIFF",
            "status": "operational" if _metadata_for_dataset("cop-dem-glo-30") else "registered",
            "source_url": "https://planetarycomputer.microsoft.com/dataset/group/copernicus-dem",
            "coverage_count": len(_metadata_for_dataset("cop-dem-glo-30")),
            "missing_data_semantics": (
                "Outside footprint or nodata; indexed coverage combines 10 pilot contexts and "
                "eight candidate-place windows. Per-context coverage is recorded in sidecars."
            ),
        },
        {
            "id": "nasadem-hgt",
            "provider": "NASA LP DAAC / NASADEM HGT",
            "name": "NASADEM merged DEM 1 arc-second HGT",
            "version": "NASADEM_HGT.001",
            "bodies": ["earth"],
            "variable": "void-filled merged elevation; NUM and SWB provenance masks",
            "units": "m relative to EGM96 geoid",
            "native_resolution_m": "approximately 30 m at equator",
            "access_method": (
                "NASA CMR granule search and Earthdata-authenticated single-tile download"
            ),
            "status": "operational" if _metadata_for_dataset("nasadem-hgt") else "registered",
            "source_url": "https://doi.org/10.5067/MEASURES/NASADEM/NASADEM_HGT.001",
            "coverage_count": len(_metadata_for_dataset("nasadem-hgt")),
            "missing_data_semantics": (
                "HGT merges SRTM and auxiliary DEM fills; paired NUM source classes and SWB "
                "water mask are recorded per granule."
            ),
        },
        {
            "id": "mola-meg128",
            "provider": "NASA Planetary Data System Geosciences Node / MGS MOLA",
            "name": "MOLA Mission Experiment Gridded Data Record topography, 128 px/degree",
            "version": "PDS4 product label 1.1; MEGDR final topography product",
            "bodies": ["mars"],
            "variable": "median observed topography relative to the areoid",
            "units": "m",
            "native_resolution_m": 463.057667,
            "spatial_coverage": (
                f"{len(_metadata_for_dataset('mola-meg128'))} indexed Mars contexts; "
                "per-region windows and observed-bin coverage are in the sidecars"
            ),
            "observation_period": "1999-03-08 through 2001-06-30",
            "crs": (
                "Mars equirectangular, east longitude, central meridian 180 degrees, R=3396000 m"
            ),
            "access_method": "PDS4 image and count product HTTP byte-range reads",
            "licence": "PDS archive citation and usage guidance",
            "uncertainty": (
                "Count grid distinguishes observed bins from interpolated bins; "
                "sparse support remains"
            ),
            "missing_data_semantics": "Zero-count bins are masked from terrain metric calculations",
            "source_url": "https://pds-geosciences.wustl.edu/missions/mgs/megdr.html",
            "status": "operational" if _metadata_for_dataset("mola-meg128") else "registered",
            "coverage_count": len(_metadata_for_dataset("mola-meg128")),
        },
        {
            "id": "lro-lola-gdr-ldem-64",
            "provider": "NASA LRO LOLA / PDS Geosciences Node",
            "name": "LOLA Gridded Data Record LDEM_64 lunar shape map",
            "version": "LRO-L-LOLA-4-GDR-V1.0; PDS3 product V3.1; created 2019-03-15",
            "bodies": ["moon"],
            "variable": "lunar radius/shape; local terrain derivatives are derived from it",
            "units": "m; signed 16-bit DN × 0.5 m relative to 1,737,400 m reference radius",
            "native_resolution_m": 473.802,
            "observation_period": "2009-07-13 through 2016-11-29",
            "spatial_coverage": (
                "Four local 22×22 cylindrical contexts (two scorecard regions and two non-polar "
                "candidate sites); south-polar candidate contexts use the separate "
                "120 m polar product"
            ),
            "crs": (
                "Simple cylindrical, east-positive, central meridian 180°, lunar radius 1,737,400 m"
            ),
            "access_method": "PDS3 IMG/LBL; bounded HTTP byte-range reads",
            "licence": "NASA PDS archive; cite the dataset/product and follow archive guidance",
            "uncertainty": (
                "Surface interpolation is used; this image has no per-pixel confidence layer"
            ),
            "missing_data_semantics": (
                "The label defines no missing-value sentinel; interpolation support is "
                "not quantified in this product"
            ),
            "source_url": "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/DATA/LOLA_GDR/CYLINDRICAL/IMG/ldem_64.lbl",
            "status": (
                "operational" if _metadata_for_dataset("lro-lola-gdr-ldem-64") else "registered"
            ),
            "coverage_count": len(_metadata_for_dataset("lro-lola-gdr-ldem-64")),
        },
        {
            "id": "lro-lola-gdr-polar-ldem-120m",
            "provider": "NASA LRO LOLA / PDS Geosciences Node",
            "name": "LOLA 75S polar elevation and direct-shot support crops",
            "version": "LRO-L-LOLA-4-GDR-V1.0; LDEM/LDEC_75S_120M; PDS3 V2.1",
            "bodies": ["moon"],
            "variable": "lunar polar elevation plus paired direct-observation counts",
            "units": "m relative to 1,737,400 m sphere; direct returns per 120 m source cell",
            "native_resolution_m": 120,
            "output_resolution_m": 463.057667,
            "observation_period": "LOLA observations through 2017-02-02",
            "spatial_coverage": (
                "Bounded crops at Shackleton, Malapert, and de Gerlache when present"
            ),
            "crs": (
                "South-polar stereographic; mean Earth/polar axis of DE421; east-p"
                "ositive; 1,737,400 m sphere"
            ),
            "access_method": (
                "PDS3 IMG/LBL; bounded HTTP byte-range reads from DEM and paired count product"
            ),
            "licence": "NASA PDS archive; cite the dataset/product and follow archive guidance",
            "uncertainty": (
                "Direct-shot counts describe support, not vertical uncertainty; no"
                " per-cell uncertainty layer is supplied."
            ),
            "missing_data_semantics": (
                "Native zero-count cells are excluded; output cells require at lea"
                "st 25% directly sampled native support."
            ),
            "source_url": "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/data/lola_gdr/polar/img/ldem_75s_120m.lbl",
            "status": "operational"
            if _metadata_for_dataset("lro-lola-gdr-polar-ldem-120m")
            else "registered",
            "coverage_count": len(_metadata_for_dataset("lro-lola-gdr-polar-ldem-120m")),
        },
        {
            "id": "lro-mini-rf-south-polar-cpr",
            "provider": "NASA LRO Mini-RF / PDS Geosciences Node",
            "name": "Mini-RF calibrated south-polar circular polarization ratio mosaic",
            "version": "LRO-L-MRFLRO-5-CDR-MOSAIC-V1.0; product LSZ_XXXXX_3CP_PFU_90S000_V1",
            "bodies": ["moon"],
            "variable": "same-sense / opposite-sense circularly polarized radar return (CPR)",
            "units": "dimensionless ratio",
            "native_resolution_m": 947.60470075467,
            "observation_period": "Combined acquisitions from 2009-07-19 through 2011-01-11",
            "spatial_coverage": (
                "5×5-pixel neighbourhoods at Shackleton, Malapert, and de Gerlache"
                " candidate-region centres"
            ),
            "crs": "South-polar stereographic; planetocentric; east-positive; 1,737.4 km sphere",
            "access_method": (
                "PDS3 calibrated mosaic; HTTP byte-range reads for site neighbourhoods only"
            ),
            "licence": "NASA PDS archive; cite the dataset/product and follow archive guidance",
            "uncertainty": (
                "No per-pixel uncertainty supplied. CPR can be elevated by roughne"
                "ss or blockiness as well as volume scattering; it is not unique e"
                "vidence of ice."
            ),
            "missing_data_semantics": (
                "PDS null and saturation sentinels are excluded from the sample statistic"
            ),
            "source_url": "https://pds-geosciences.wustl.edu/lro/lro-l-mrflro-4-cdr-v1/lromrf_0005/data/sar/mosaics/lsz_xxxxx_3cp_pfu_90s000_v1.lbl",
            "status": "operational"
            if next(
                (
                    item["status"]
                    for item in analogue.source_inventory(ROOT)
                    if item["id"] == "mini-rf-cpr"
                ),
                "registered",
            )
            == "operational"
            else "registered",
            "coverage_count": next(
                (
                    item["coverage_count"]
                    for item in analogue.source_inventory(ROOT)
                    if item["id"] == "mini-rf-cpr"
                ),
                0,
            ),
            "scorecard_role": (
                "context clue only; excluded from analogue similarity and mission suitability"
            ),
        },
        {
            "id": "lro-lend-south-polar-alds",
            "provider": "NASA LRO Lunar Exploration Neutron Detector / PDS Geosciences Node",
            "name": "LEND averaged south-polar CSETN neutron count rates",
            "version": "LRO-L-LEND-4/5-RDR-V1.0; ALDS products 2009-09-15 and 2011-12-11",
            "bodies": ["moon"],
            "variable": "CSETN normalized neutron count rate and product statistical error",
            "units": "counts/s",
            "native_resolution_m": (
                "0.5° map grid; physical cell size varies with latitude and is not"
                " the full instrument footprint"
            ),
            "observation_period": (
                "2009-09-15 through 2016-09-14 across two ALDS product periods; la"
                "ter RDR_DLD records are not connected"
            ),
            "spatial_coverage": (
                "Three south-polar candidate grid cells; missing CSETN values remain unavailable"
            ),
            "access_method": (
                "PDS3 ALDS fixed-record tables; HTTP byte-range reads of selected "
                "310-byte map-cell rows"
            ),
            "licence": "NASA PDS archive; cite the dataset/product and follow archive guidance",
            "uncertainty": (
                "CSETN_ERR is the supplied statistical error only; spatial footpri"
                "nt and systematic uncertainty are not combined."
            ),
            "source_url": "https://pds-geosciences.wustl.edu/missions/lro/lend.htm",
            "status": "operational"
            if next(
                (
                    item["status"]
                    for item in analogue.source_inventory(ROOT)
                    if item["id"] == "lunar-lend"
                ),
                "registered",
            )
            == "operational"
            else "registered",
            "coverage_count": next(
                (
                    item["coverage_count"]
                    for item in analogue.source_inventory(ROOT)
                    if item["id"] == "lunar-lend"
                ),
                0,
            ),
            "scorecard_role": (
                "indirect hydrogen context only; not water/ice confirmation and not scored"
            ),
        },
        {
            "id": "lro-diviner-prp-south-polar",
            "provider": "NASA LRO Diviner / PDS Geosciences Node",
            "name": "Diviner south-polar Polar Resource Product (PRP)",
            "version": "LRO-L-DLRE-5-PRP-V2.0; DLRE_PRP_SOUTH.TAB",
            "bodies": ["moon"],
            "variable": "modeled annual surface temperature and water-ice stability depth",
            "units": "K; m",
            "native_resolution_m": "about 0.5 km triangular mesh",
            "observation_period": (
                "Thermal-model fit to Diviner observations from the first mapping year"
            ),
            "spatial_coverage": (
                "Nearest triangle-centroid samples for Shackleton, Malapert, and d"
                "e Gerlache candidates"
            ),
            "access_method": (
                "PDS3 fixed-length ASCII table; bounded HTTP byte-range reads for nearby mesh rows"
            ),
            "licence": "NASA PDS archive; cite the dataset/product and follow archive guidance",
            "uncertainty": (
                "No per-triangle uncertainty field is supplied; model uncertainty "
                "is not quantified in ENOM."
            ),
            "missing_data_semantics": (
                "PDS -999 ice_depth means the modeled threshold is beyond 2.8738 m"
                "; ENOM reports it as not_reported, not zero."
            ),
            "source_url": "https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_prp/dlre_prp_south.lbl",
            "status": "operational"
            if next(
                (
                    item["status"]
                    for item in analogue.source_inventory(ROOT)
                    if item["id"] == "diviner-prp"
                ),
                "registered",
            )
            == "operational"
            else "registered",
            "coverage_count": next(
                (
                    item["coverage_count"]
                    for item in analogue.source_inventory(ROOT)
                    if item["id"] == "diviner-prp"
                ),
                0,
            ),
            "scorecard_role": (
                "lunar modeled context only; not direct ice detection, cross-body "
                "score, or mission-suitability input"
            ),
        },
        {
            "id": "lro-diviner-gdr-level3-st-clc",
            "provider": "NASA LRO Diviner / PDS Geosciences Node",
            "name": "Diviner nighttime rock-free regolith surface-temperature context",
            "version": "LRO-L-DLRE-5-GDR-V1.0; PDS3 V6.0",
            "bodies": ["moon"],
            "variable": "product-derived nighttime rock-free regolith surface temperature",
            "units": "K; signed 16-bit little-endian DN × 0.02 K; -32768 is missing",
            "native_resolution_m": 236.901175,
            "observation_period": "algorithm input spans 2009-07-05 through 2016-10-10",
            "crs": "Simple cylindrical; planetocentric latitude; east-positive longitude",
            "access_method": "PDS3 IMG/LBL; bounded HTTP byte-range reads",
            "licence": "NASA PDS archive; cite the dataset/product and follow archive guidance",
            "uncertainty": (
                "Derived rock-free regolith temperature; most surface cells have a single "
                "observation and repeat-observation counts are not supplied in this crop"
            ),
            "missing_data_semantics": "The PDS label defines -32768 as missing",
            "source_url": "https://pds-geosciences.wustl.edu/missions/lro/diviner.htm",
            "status": (
                "operational"
                if _metadata_for_dataset("lro-diviner-gdr-level3-st-clc")
                else "registered"
            ),
            "coverage_count": len(_metadata_for_dataset("lro-diviner-gdr-level3-st-clc")),
        },
        {
            "id": "mgs-tes-derived-thermal-inertia",
            "provider": "NASA MGS TES / PDS Geosciences Node",
            "name": "TES nightside derived thermal inertia map",
            "version": "MGS-M-TES-5-TIMAP-V1.0; GLOBAL_TI_NIGHT_2007",
            "bodies": ["mars"],
            "variable": "derived surface thermal inertia; not temperature",
            "units": "J/(m^2*K*sqrt(s))",
            "native_resolution_m": 2960.0,
            "observation_period": "TES observations, 1999-02 through 2004-04",
            "crs": (
                "Simple cylindrical; planetocentric latitude; east-positive longitude; "
                "3396 km sphere"
            ),
            "access_method": (
                "PDS3 IMG/LBL; bounded HTTP byte-range reads with paired interpolation mask"
            ),
            "licence": "NASA PDS archive; cite the dataset/product and follow archive guidance",
            "uncertainty": (
                "Derived global map; paired mask identifies interpolated cells, "
                "no per-cell uncertainty included"
            ),
            "missing_data_semantics": "Mask value 0 denotes cells infilled by interpolation",
            "source_url": "https://pds-geosciences.wustl.edu/missions/mgs/tes-timap.html",
            "status": "operational"
            if _metadata_for_dataset("mgs-tes-derived-thermal-inertia")
            else "registered",
            "coverage_count": len(_metadata_for_dataset("mgs-tes-derived-thermal-inertia")),
        },
        {
            "id": "nasa-power-climatology",
            "provider": "NASA Langley Research Center POWER project",
            "name": "POWER gridded annual and monthly point climatology",
            "version": _nasa_power_version(),
            "bodies": ["earth"],
            "variable": (
                "2 m air temperature and relative humidity, 10 m wind speed, all-s"
                "ky surface shortwave radiation"
            ),
            "units": "°C; %; m/s; kWh/m²/day",
            "native_resolution_m": (
                "Meteorology grid: 0.5° × 0.625°; solar radiation grid: 1° × 1°. N"
                "ASA POWER point values represent these source grid cells, not loc"
                "al sensors."
            ),
            "access_method": (
                "NASA POWER Climatology API; eight compact point responses cached locally"
            ),
            "status": "operational" if _nasa_power_records() else "not_observed",
            "source_url": "https://power.larc.nasa.gov/docs/services/api/temporal/climatology/",
            "coverage_count": len(_nasa_power_records()),
            "observation_period": (
                "per-record period field; POWER response identifies Jan 2001–Dec 2025"
            ),
            "uncertainty": (
                "Gridded climatology/reanalysis estimate; not in-situ site measurements."
            ),
            "missing_data_semantics": (
                "NASA POWER fill values are converted to explicit not_observed values."
            ),
        },
        {
            "id": "era5-earth-candidate-climatology",
            "provider": "ECMWF/Copernicus ERA5 via Open-Meteo Historical Weather API",
            "name": "ERA5 Earth candidate-place monthly climate summaries",
            "version": "ERA5; 1991–2020 baseline; daily API values summarized by calendar month",
            "bodies": ["earth"],
            "variable": "2 m air temperature, 10 m wind speed, monthly precipitation total",
            "units": "°C; m/s; mm/month",
            "native_resolution_m": (
                "0.25° grid, about 25 km; nearest returned grid point is recorded per candidate"
            ),
            "access_method": (
                "Open-Meteo Historical Weather API ERA5 model; compact monthly sum"
                "maries cached locally"
            ),
            "status": "operational"
            if any(
                item.get("dataset_id") == "era5-earth-candidate-climatology"
                for item in analogue.source_inventory(ROOT)
            )
            else "registered",
            "source_url": "https://open-meteo.com/en/docs/historical-weather-api",
            "coverage_count": next(
                (
                    item.get("coverage_count", 0)
                    for item in analogue.source_inventory(ROOT)
                    if item.get("dataset_id") == "era5-earth-candidate-climatology"
                ),
                0,
            ),
            "observation_period": "1991-01-01 through 2020-12-31 climate baseline",
            "uncertainty": (
                "ERA5 reanalysis is a model grid rather than local weather-station"
                " data; grid-point snapping and full uncertainty ranges are not pr"
                "opagated."
            ),
            "missing_data_semantics": (
                "Missing daily values are excluded from monthly summaries; months "
                "with no valid values remain null."
            ),
            "scorecard_role": (
                "Earth climate context only; not used in cross-body analogue simil"
                "arity or mission suitability."
            ),
        },
        {
            "id": "mars2020-meda",
            "provider": "NASA Planetary Data System Atmospheres Node",
            "name": "Mars 2020 MEDA selected-sol environmental records",
            "version": "PDS4 Mars 2020 MEDA bundle 6.0; one-sol ENOM summaries",
            "bodies": ["mars"],
            "variable": (
                "near-surface air temperature, relative humidity, and horizontal wind speed"
            ),
            "units": "K; %RH; m/s",
            "native_resolution_m": (
                "Rover-mounted point sensors; rover track location varies within Jezero"
            ),
            "access_method": (
                "PDS Atmospheres Node CSV products summarized locally for Mars sol"
                " 100; raw CSV files are not retained"
            ),
            "status": "operational" if _meda_records() else "registered",
            "source_url": "https://pds.nasa.gov/ds-view/pds/viewBundle.jsp?identifier=urn:nasa:pds:mars2020_meda&version=1.0",
            "coverage_count": len(_meda_records()),
            "observation_period": "Mars sol 100 only; not a climate normal",
            "uncertainty": (
                "PDS product-level uncertainty and valid sample counts are preserv"
                "ed; source flags and short temporal coverage limit interpretation"
                "."
            ),
            "missing_data_semantics": (
                "PDS fill values and non-finite values are excluded from each one-sol summary."
            ),
        },
        {
            "id": "mars2020-rover-places-best-tactical",
            "provider": "NASA Mars 2020 Rover PLACES / PDS Geosciences Node",
            "name": "Perseverance best-tactical drive localizations near Jezero",
            "version": "Mars 2020 Rover PLACES Release 16; Jezero-region subset",
            "bodies": ["mars"],
            "variable": "planetocentric rover position fixes associated with drive records",
            "units": "degrees; elevation m; Mars sol and site/drive indices",
            "native_resolution_m": (
                "Per-position localization; no uncertainty field in the connected CSV"
            ),
            "spatial_coverage": (
                "577 selected drive positions within 20 km of ENOM's Jezero candidate coordinate"
            ),
            "access_method": (
                "PDS PLACES best_tactical.csv; only candidate-region rows are retained in ENOM"
            ),
            "licence": "NASA PDS archive; cite the dataset/product and follow archive guidance",
            "uncertainty": (
                "The source table provides coordinates but no per-position uncerta"
                "inty estimate in this ingest."
            ),
            "missing_data_semantics": (
                "SITE rows and invalid sol/drive entries are excluded; missing dri"
                "ve locations are not interpolated."
            ),
            "source_url": "https://pds-geosciences.wustl.edu/missions/mars2020/places.htm",
            "status": "operational"
            if next(
                (
                    item["status"]
                    for item in analogue.source_inventory(ROOT)
                    if item["id"] == "mars2020-rover-places"
                ),
                "registered",
            )
            == "operational"
            else "registered",
            "coverage_count": next(
                (
                    item["coverage_count"]
                    for item in analogue.source_inventory(ROOT)
                    if item["id"] == "mars2020-rover-places"
                ),
                0,
            ),
            "scorecard_role": (
                "Discrete operation context only; not a continuous traverse, rover"
                "-safety test, or suitability score"
            ),
        },
        {
            "id": "usgs-earth-sgmc",
            "provider": "U.S. Geological Survey / State Geological Surveys",
            "name": "State Geologic Map Compilation (SGMC)",
            "version": (
                "Conterminous United States regional compilation; source maps rang"
                "e approximately 1:50,000–1:1,000,000"
            ),
            "bodies": ["earth"],
            "variable": "mapped geologic unit, generalized lithology, age and major materials",
            "units": "categorical map interpretation",
            "native_resolution_m": (
                "varies by contributing state map; not a uniform pixel resolution"
            ),
            "crs": "Source layer NAD83 (EPSG:4269); point queries submitted in WGS 84",
            "access_method": (
                "USGS ArcGIS FeatureServer point query; candidate result sidecars cached locally"
            ),
            "licence": "USGS/state compilation attribution; follow source map citations",
            "uncertainty": (
                "State maps vary in scale and units are not fully reconciled acros"
                "s state boundaries; not a local assay."
            ),
            "missing_data_semantics": (
                "Only three of eight catalogue candidates fall within this CONUS l"
                "ayer; outside-extent places remain explicit."
            ),
            "source_url": "https://doi.org/10.5066/F7WH2N65",
            "status": "operational" if _earth_geology_records(mapped_only=True) else "registered",
            "coverage_count": len(_earth_geology_records(mapped_only=True)),
        },
        {
            "id": "usgs-sim-1083-mars-global-geology",
            "provider": "U.S. Geological Survey Astrogeology Science Center",
            "name": "Global Mars geologic map unit polygons",
            "version": "USGS SIM 1083; Scott and Carr global geologic map renovation",
            "bodies": ["mars"],
            "variable": "categorical mapped geologic unit code",
            "units": "unit code (categorical)",
            "native_resolution_m": "regional map scale; varies by latitude",
            "crs": "Mars 2000 sphere geographic, radius 3,396,190 m",
            "access_method": "Public USGS ScienceBase ZIP; cached locally; point-in-polygon lookup",
            "licence": "USGS data release marked CC0 1.0 Universal",
            "uncertainty": (
                "Generalized map-unit classification; not local soil or engineering evidence"
            ),
            "missing_data_semantics": "Unmapped or boundary-ambiguous points remain unavailable",
            "source_url": "https://doi.org/10.5066/P9UGAC18",
            "status": "operational" if _mars_geology_records() else "registered",
            "coverage_count": len(_mars_geology_records()),
        },
        {
            "id": "usgs-fortezzo-2020-unified-lunar-geology",
            "provider": "U.S. Geological Survey Astrogeology Science Center",
            "name": "Unified Geologic Map of the Moon, GeoUnits_Mercator layer",
            "version": "Fortezzo, Spudis, and Harrel (2020); 49 units at 1:5,000,000 scale",
            "bodies": ["moon"],
            "variable": "categorical regional geologic unit, age, and interpretation",
            "units": "unit code and mapped descriptions (categorical)",
            "native_resolution_m": "1:5,000,000 cartographic scale; not a pixel resolution",
            "crs": "Moon_2000 spherical Mercator; radius 1,737,400 m; central meridian 0°",
            "access_method": "Public USGS ArcGIS service; bounded point query",
            "licence": (
                "Service metadata has no explicit licence; preserve USGS/map-author attribution"
            ),
            "uncertainty": "Regional interpretation; not a local assay or engineering property",
            "missing_data_semantics": (
                "Outside extent, unmapped, and boundary-ambiguous states are explicit"
            ),
            "source_url": "https://astrogeology.usgs.gov/search/map/Moon/Geology/Unified_Geologic_Map_of_the_Moon_GIS_v2/",
            "status": "operational" if _lunar_geology_records() else "registered",
            "coverage_count": len(_lunar_geology_records()),
        },
    ]


@app.get("/api/datasets/{dataset_id}/coverage")
def dataset_coverage(dataset_id: str) -> dict[str, object]:
    """Describe indexed coverage and the dataset's observation-level limits."""
    if dataset_id in {"candidate-subsurface-context", "candidate-mission-site-context"}:
        rows = [
            row
            for row in analogue.candidate_context_records(ROOT)
            if row["dataset_id"] == dataset_id
        ]
        body_counts = {
            body: sum(row["body"] == body for row in rows)
            for body in sorted({str(row["body"]) for row in rows})
        }
        return {
            "dataset_id": dataset_id,
            "observation_ids": [row["place_id"] for row in rows],
            "coverage_count": len(rows),
            "status": "context_only" if rows else "not_observed",
            "body_counts": body_counts,
            "observations": rows,
            "measurement_status": (
                "No measurements; these are source-linked catalogue interpretations."
            ),
        }
    if dataset_id == "mars2020-meda":
        rows = _meda_records()
        path = ROOT / "data/environment/mars2020-meda-sol100.json"
        payload = (
            json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"records": []}
        )
        return {
            "dataset_id": dataset_id,
            "observation_ids": [row["observation_id"] for row in rows],
            "coverage_count": len(rows),
            "unique_place_count": len({row["place_id"] for row in rows}),
            "status": "available" if rows else "not_observed",
            "body_counts": {"mars": len(rows)} if rows else {},
            "observations": rows,
            "scope": payload.get("scope"),
            "measurement_semantics": (
                "One-sol sample summaries; not a climate normal and not used for E"
                "arth analogue scoring."
            ),
        }
    if dataset_id == "mars2020-rover-places-best-tactical":
        path = ROOT / "data/environment/mars2020-jezero-rover-places.json"
        payload = (
            json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"records": []}
        )
        rows = payload.get("records", [])
        sols = [int(row["sol"]) for row in rows]
        return {
            "dataset_id": dataset_id,
            "observation_ids": [row["observation_id"] for row in rows],
            "place_ids": [payload["place_id"]] if rows else [],
            "coverage_count": len(rows),
            "unique_place_count": 1 if rows else 0,
            "status": "context_only" if rows else "not_observed",
            "body_counts": {"mars": 1} if rows else {},
            "observations": rows,
            "measurement_semantics": (
                "Selected best-tactical rover positions associated with drive reco"
                "rds; discrete fixes are not a continuous wheel path."
            ),
            "temporal_coverage": f"Mars sols {min(sols)}–{max(sols)}" if sols else None,
            "spatial_coverage": f"Positions within {
                payload.get('candidate_region_radius_km')
            } km of the Jezero candidate coordinate.",
            "uncertainty_semantics": payload.get("position_uncertainty"),
            "interpretation_limit": payload.get("interpretation_limit"),
            "release_url": payload.get("release_url"),
            "scoring_role": (
                "Operational context only; not included in analogue similarity or "
                "mission suitability."
            ),
        }
    if dataset_id == "lro-lola-gdr-ldem-64":
        metadata = _metadata_for_dataset(dataset_id)
        return {
            "dataset_id": dataset_id,
            "observation_ids": [row["observation_id"] for row in metadata],
            "coverage_count": len(metadata),
            "status": "available" if metadata else "not_observed",
            "body_counts": {"moon": len(metadata)},
            "observations": metadata,
            "observation_coverage_semantics": (
                "Raster-valid-pixel fraction is not direct LOLA shot coverage; "
                "the latter is not quantified by this product/crop."
            ),
        }
    if dataset_id == "lro-lola-gdr-polar-ldem-120m":
        metadata = _metadata_for_dataset(dataset_id)
        return {
            "dataset_id": dataset_id,
            "observation_ids": [str(row["observation_id"]) for row in metadata],
            "coverage_count": len(metadata),
            "status": "available" if metadata else "not_observed",
            "body_counts": {"moon": len(metadata)} if metadata else {},
            "place_ids": [str(row["place_id"]) for row in metadata],
            "observations": metadata,
            "support_semantics": (
                "Paired LDEC product reports direct laser observations per native 120 m cell. "
                "ENOM masks unsupported native cells and requires at least 25% support within "
                "each 463 m comparison-grid cell. This is coverage support, "
                "not vertical uncertainty."
            ),
        }
    if dataset_id == "lro-mini-rf-south-polar-cpr":
        path = ROOT / "data/environment/lro-mini-rf-south-polar-cpr.json"
        payload = (
            json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"records": []}
        )
        rows = payload.get("records", [])
        return {
            "dataset_id": dataset_id,
            "observation_ids": [row["observation_id"] for row in rows],
            "place_ids": [row["place_id"] for row in rows],
            "coverage_count": len(rows),
            "status": "context_only" if rows else "not_observed",
            "body_counts": {"moon": len(rows)} if rows else {},
            "observations": rows,
            "measurement_semantics": (
                "Median circular polarization ratio over a 5×5-pixel neighbourhood"
                ", about 948 m per pixel."
            ),
            "interpretation_limit": (
                "CPR can reflect surface roughness/blockiness or volume scattering"
                "; it does not uniquely detect water ice or establish resource usa"
                "bility."
            ),
            "retrieval_method": payload.get("retrieval_method"),
            "scoring_role": (
                "Context only; not used for analogue similarity or mission suitability."
            ),
        }
    if dataset_id == "lro-lend-south-polar-alds":
        path = ROOT / "data/environment/lro-lend-south-polar-alds.json"
        payload = (
            json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"records": []}
        )
        rows = payload.get("records", [])
        return {
            "dataset_id": dataset_id,
            "observation_ids": [row["observation_id"] for row in rows],
            "place_ids": sorted({row["place_id"] for row in rows}),
            "coverage_count": len(rows),
            "unique_place_count": len({row["place_id"] for row in rows}),
            "status": "context_only" if rows else "not_observed",
            "body_counts": {"moon": len({row["place_id"] for row in rows})} if rows else {},
            "observations": rows,
            "measurement_semantics": (
                "CSETN normalized neutron count rate for the matching 0.5° south-p"
                "olar ALDS map cell."
            ),
            "temporal_coverage_limit": (
                "These averaged ALDS products end in 2016; newer LEND RDR_DLD reco"
                "rds are not included in ENOM."
            ),
            "missing_data_semantics": (
                "CSETN rows with zero exposure, -1 rate or -1 error are exposed as"
                " not_observed, not as zero similarity or absence of hydrogen."
            ),
            "uncertainty_semantics": (
                "CSETN_ERR is statistical error only; it does not combine instrume"
                "nt footprint, cell-location, or systematic uncertainty."
            ),
            "interpretation_limit": (
                "Neutron rate is indirect hydrogen context, not a direct water/ice"
                " measurement or usable-resource estimate."
            ),
            "retrieval_method": payload.get("retrieval_method"),
            "scoring_role": (
                "Context only; not used for analogue similarity or mission suitability."
            ),
        }
    if dataset_id == "lro-diviner-prp-south-polar":
        path = ROOT / "data/environment/lro-diviner-south-polar-prp.json"
        payload = (
            json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"records": []}
        )
        rows = payload.get("records", [])
        return {
            "dataset_id": dataset_id,
            "observation_ids": [row["observation_id"] for row in rows],
            "place_ids": sorted({row["place_id"] for row in rows}),
            "coverage_count": len(rows),
            "unique_place_count": len({row["place_id"] for row in rows}),
            "status": "context_only" if rows else "not_observed",
            "body_counts": {"moon": len({row["place_id"] for row in rows})} if rows else {},
            "observations": rows,
            "measurement_semantics": (
                "Nearest triangular-mesh centroid sample of model-derived annual t"
                "emperatures and ice-stability depth."
            ),
            "missing_data_semantics": (
                "PDS -999 ice-depth values mean the modeled threshold exceeds 2.87"
                "38 m; shown as not_reported."
            ),
            "uncertainty_semantics": (
                "The product has no per-triangle uncertainty field; model uncertai"
                "nty is not propagated."
            ),
            "interpretation_limit": (
                "A thermal-model estimate from first-year Diviner observations, no"
                "t direct detection or confirmation of accessible water ice."
            ),
            "retrieval_method": payload.get("retrieval_method"),
            "scoring_role": (
                "Lunar context only; not used for analogue similarity or mission suitability."
            ),
        }
    if dataset_id == "nasa-power-climatology":
        rows = _nasa_power_records()
        return {
            "dataset_id": dataset_id,
            "observation_ids": [row["place_id"] for row in rows],
            "coverage_count": len(rows),
            "status": "available" if rows else "not_observed",
            "body_counts": {"earth": len(rows)},
            "observations": rows,
            "uncertainty_semantics": (
                "NASA POWER gridded climatology, not local station observations."
            ),
        }
    if dataset_id == "era5-earth-candidate-climatology":
        path = ROOT / "data/environment/era5-earth-candidate-climatology.json"
        payload = (
            json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"records": []}
        )
        rows = payload.get("records", [])
        return {
            "dataset_id": dataset_id,
            "observation_ids": [row["observation_id"] for row in rows],
            "place_ids": [row["place_id"] for row in rows],
            "coverage_count": len(rows),
            "unique_place_count": len({row["place_id"] for row in rows}),
            "status": "context_only" if rows else "not_observed",
            "body_counts": {"earth": len({row["place_id"] for row in rows})} if rows else {},
            "observations": rows,
            "measurement_semantics": (
                "1991–2020 ERA5 daily reanalysis summarized into monthly 2 m tempe"
                "rature, 10 m wind, and precipitation climatologies at nearest 0.2"
                "5° grid points."
            ),
            "uncertainty_semantics": (
                "Grid-point offset and nominal resolution are retained; reanalysis"
                " and spatial uncertainty are not combined into total error bars."
            ),
            "interpretation_limit": (
                "Not local station data; air temperature, wind, and precipitation "
                "do not directly measure surface material, dust events, soil water"
                ", or resource usability."
            ),
            "scoring_role": "Context only; no validated cross-body comparison is connected.",
        }
    if dataset_id == "mgs-tes-derived-thermal-inertia":
        metadata = _metadata_for_dataset(dataset_id)
        return {
            "dataset_id": dataset_id,
            "observation_ids": [str(row["observation_id"]) for row in metadata],
            "coverage_count": len(metadata),
            "status": "available" if metadata else "not_observed",
            "body_counts": {"mars": len(metadata)},
            "observations": metadata,
            "scorecard_role": (
                "derived thermal inertia context only; not temperature and not sco"
                "red against Earth air temperature."
            ),
        }
    records, _, _ = _load()
    if dataset_id == "pilot-surface-imagery":
        subset = records
        return {
            "dataset_id": dataset_id,
            "observation_ids": [record.image_id for record in subset],
            "coverage_count": len(subset),
            "status": "available" if subset else "not_observed",
            "body_counts": {
                body: sum(record.body == body for record in subset) for body in ("earth", "mars")
            },
        }
    if dataset_id == "cop-dem-glo-30":
        available = _metadata_for_dataset("cop-dem-glo-30")
        ids = [row["observation_id"] for row in available]
        return {
            "dataset_id": dataset_id,
            "observation_ids": ids,
            "coverage_count": len(ids),
            "status": "available" if ids else "not_observed",
            "body_counts": {"earth": len(ids)},
        }
    if dataset_id == "mola-meg128":
        metadata = _metadata_for_dataset("mola-meg128")
        ids = [row["observation_id"] for row in metadata]
        return {
            "dataset_id": dataset_id,
            "observation_ids": ids,
            "coverage_count": len(ids),
            "status": "available" if ids else "not_observed",
            "body_counts": {"mars": len(ids)},
            "observations": metadata,
            "missing_data_semantics": [row.get("missing_data_semantics") for row in metadata],
        }
    if dataset_id == "lro-diviner-gdr-level3-st-clc":
        metadata = _metadata_for_dataset(dataset_id)
        ids = [str(row["observation_id"]) for row in metadata]
        return {
            "dataset_id": dataset_id,
            "observation_ids": ids,
            "coverage_count": len(ids),
            "status": "available" if ids else "not_observed",
            "body_counts": {"moon": len(ids)},
            "observations": metadata,
            "scorecard_role": "environmental evidence only; excluded from terrain ranking",
        }
    if dataset_id == "usgs-sim-1083-mars-global-geology":
        metadata = _mars_geology_records()
        return {
            "dataset_id": dataset_id,
            "observation_ids": [str(row["observation_id"]) for row in metadata],
            "coverage_count": len(metadata),
            "status": "available" if metadata else "not_observed",
            "body_counts": {"mars": len(metadata)},
            "observations": metadata,
            "scorecard_role": "categorical geological context only; excluded from terrain ranking",
        }
    if dataset_id == "usgs-fortezzo-2020-unified-lunar-geology":
        metadata = _lunar_geology_records()
        return {
            "dataset_id": dataset_id,
            "observation_ids": [str(row["observation_id"]) for row in metadata],
            "coverage_count": len(metadata),
            "status": "available" if metadata else "not_observed",
            "body_counts": {"moon": len(metadata)},
            "observations": metadata,
            "scorecard_role": (
                "categorical regional interpretation; no mineral assay or terrain score."
            ),
        }
    if dataset_id == "usgs-earth-sgmc":
        metadata = _earth_geology_records()
        mapped = [
            row
            for row in metadata
            if row.get("classification_status") in {"mapped", "boundary_ambiguous"}
        ]
        return {
            "dataset_id": dataset_id,
            "observation_ids": [str(row["observation_id"]) for row in mapped],
            "coverage_count": len(mapped),
            "candidate_site_query_count": len(metadata),
            "status": "available" if mapped else "not_observed",
            "body_counts": {"earth": len(mapped)},
            "observations": metadata,
            "coverage_notes": [
                str(row["observation_id"]) + ": " + str(row["classification_status"])
                for row in metadata
            ],
            "scorecard_role": (
                "regional categorical geology context only; excluded from similarity scoring."
            ),
        }
    if dataset_id == "lro-lola-gdr-ldem-64":
        metadata = _metadata_for_dataset(dataset_id)
        ids = [str(row["observation_id"]) for row in metadata]
        return {
            "dataset_id": dataset_id,
            "observation_ids": ids,
            "coverage_count": len(ids),
            "status": "available" if ids else "not_observed",
            "body_counts": {"moon": len(ids)},
            "observations": metadata,
            "missing_data_semantics": [row.get("missing_data_semantics") for row in metadata],
        }
    raise HTTPException(404, detail="Dataset is not registered")


@app.get("/api/profiles")
def profiles() -> list[dict[str, object]]:
    return [
        {
            "id": "aeolian",
            "name": "Aeolian / sediment transport",
            "status": "visual retrieval only",
            "criteria": ["surface morphology"],
            "limitations": ["No DEM, sediment properties or wind measurements are indexed"],
        },
        {
            "id": "rover_mobility",
            "name": "Rover mobility",
            "status": "not implemented",
            "criteria": [],
            "limitations": ["Orbital imagery alone cannot establish traversability"],
        },
        {
            "id": "ancient_water",
            "name": "Ancient water-related processes",
            "status": "not implemented",
            "criteria": [],
            "limitations": [],
        },
        {
            "id": "volcanic",
            "name": "Volcanic geology",
            "status": "not implemented",
            "criteria": [],
            "limitations": [],
        },
    ]


@app.get("/api/regions")
def regions(body: str | None = None, limit: int = 200) -> list[dict[str, object]]:
    """List pilot regions, optionally filtered by body and bounded result count."""
    records, _, _ = _load()
    return [_record_payload(r) for r in records if body is None or r.body == body][
        : max(1, min(limit, 500))
    ]


@app.get("/api/regions/{observation_id}")
def region(observation_id: str) -> dict[str, object]:
    """Return provenance and evidence metadata for one indexed observation."""
    records, indexes, _ = _load()
    if observation_id not in indexes:
        raise HTTPException(
            404, detail={"code": "observation_not_found", "message": "Observation is not indexed"}
        )
    return _record_payload(records[indexes[observation_id]])


@app.get("/api/observations/{observation_id}")
def observation(observation_id: str) -> dict[str, object]:
    return region(observation_id)


@app.get("/api/observations/{observation_id}/image")
def observation_image(observation_id: str) -> Response:
    """Render an indexed raster as a display-sized JPEG preview."""
    records, indexes, _ = _load()
    if observation_id not in indexes:
        raise HTTPException(404, detail="Observation is not indexed")
    record = records[indexes[observation_id]]
    path = ROOT / record.path
    if not path.is_file():
        raise HTTPException(404, detail="Source image asset is unavailable locally")
    with rasterio.open(path) as ds:
        if ds.count >= 3:
            pixels = np.stack([ds.read(b, masked=True).filled(np.nan) for b in (1, 2, 3)], axis=-1)
            valid = np.isfinite(pixels).all(axis=-1)
            if not valid.any():
                raise HTTPException(422, detail="Image has no valid pixels")
            out = np.zeros((*pixels.shape[:2], 3), dtype=np.uint8)
            for band in range(3):
                lo, hi = np.percentile(pixels[..., band][valid], [2, 98])
                out[..., band] = np.clip(
                    np.nan_to_num(
                        (pixels[..., band] - lo) / max(hi - lo, 1e-9) * 255,
                        nan=0.0,
                        posinf=255.0,
                        neginf=0.0,
                    ),
                    0,
                    255,
                ).astype(np.uint8)
        else:
            pixels = ds.read(1, masked=True).filled(np.nan)
            valid = np.isfinite(pixels)
            if not valid.any():
                raise HTTPException(422, detail="Image has no valid pixels")
            lo, hi = np.percentile(pixels[valid], [2, 98])
            out = np.clip(
                np.nan_to_num(
                    (pixels - lo) / max(hi - lo, 1e-9) * 255,
                    nan=0.0,
                    posinf=255.0,
                    neginf=0.0,
                ),
                0,
                255,
            ).astype(np.uint8)
    image = Image.fromarray(out)
    image.thumbnail((900, 900))
    data = io.BytesIO()
    image.save(data, format="JPEG", quality=86)
    return Response(
        data.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"}
    )


@app.post("/api/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    """Rank cross-body image candidates and expose terrain eligibility separately."""
    records, indexes, vectors = _load()
    if request.observation_id not in indexes:
        raise HTTPException(
            404,
            detail={
                "code": "observation_not_found",
                "message": "Selected region is outside the indexed pilot",
            },
        )
    query_index = indexes[request.observation_id]
    query = records[query_index]
    if query.body == "moon":
        raise HTTPException(
            422,
            detail={
                "code": "unsupported_body",
                "message": "Moon retrieval is not currently indexed",
            },
        )
    visual_results = visual_search(vectors, records, query_index, top_k=max(1, len(records)))
    candidate_indices = [index for index, _ in visual_results]
    score_by_index = dict(visual_results)
    visual_ranks = {index: rank for rank, (index, _) in enumerate(visual_results, start=1)}
    all_ids = [record.image_id for record in records]
    terrain_scores = {
        index: _terrain_similarity(query.image_id, records[index].image_id, all_ids)
        for index in candidate_indices
    }
    terrain_order = sorted(
        (i for i in candidate_indices if terrain_scores[i] is not None),
        key=lambda i: (-float(terrain_scores[i] or 0.0), i),
    )
    eligible = [i for i in candidate_indices if terrain_scores[i] is not None]
    visual_min = min(score_by_index.values(), default=0.0)
    visual_max = max(score_by_index.values(), default=1.0)
    visual_norm = {
        index: (score_by_index[index] - visual_min) / max(visual_max - visual_min, 1e-9)
        for index in candidate_indices
    }
    combined = {
        index: 0.5 * visual_norm[index] + 0.5 * float(terrain_scores[index] or 0.0)
        for index in eligible
    }
    combined_order = sorted(eligible, key=lambda i: (-combined[i], i))
    eligible_visual_order = sorted(eligible, key=lambda i: (-score_by_index[i], i))
    eligible_visual_ranks = {index: rank for rank, index in enumerate(eligible_visual_order, 1)}
    if request.method == "visual":
        selected_order = list(visual_ranks)
    elif request.method == "terrain":
        selected_order = terrain_order
    else:
        selected_order = combined_order if combined_order else list(visual_ranks)
    selected_order = selected_order[: request.limit]
    results: list[SearchResult] = []
    for rank, index in enumerate(selected_order, start=1):
        candidate = records[index]
        terrain_score = terrain_scores[index]
        results.append(
            SearchResult(
                observation_id=candidate.image_id,
                rank=rank,
                cosine_similarity=score_by_index[index],
                terrain_similarity=terrain_score,
                combined_score=combined.get(index),
                visual_rank=visual_ranks[index],
                rank_change_from_visual=visual_ranks[index] - rank,
                eligible_visual_rank=eligible_visual_ranks.get(index),
                rank_change_within_eligible=(
                    eligible_visual_ranks[index] - rank if index in eligible_visual_ranks else None
                ),
                ranking_evidence=(
                    ["visual_embedding"]
                    if request.method == "visual"
                    else ["terrain_measurements"]
                    if request.method == "terrain"
                    else (
                        ["visual_embedding", "terrain_measurements"]
                        if terrain_score is not None
                        else ["visual_embedding"]
                    )
                ),
                terrain_quality=_terrain_quality(candidate.image_id),
                retrieval_method=(
                    "DINOv2 exact cosine"
                    if request.method == "visual"
                    else "scale-matched robust terrain feature similarity"
                    if request.method == "terrain"
                    else "equal-weight min-max visual and robust terrain similarity"
                ),
                source_url=candidate.source_url,
                location={
                    "body": candidate.body,
                    "longitude_east_deg": (
                        candidate.longitude % 360.0
                        if candidate.body == "mars"
                        else candidate.longitude
                    ),
                    "latitude_deg": candidate.latitude,
                    "geographic_group": candidate.geographic_group,
                },
                image_url=f"/api/observations/{candidate.image_id}/image",
                evidence=[
                    EvidenceRecord(
                        category="surface imagery",
                        status=Availability.AVAILABLE,
                        summary=(
                            "Source image and precomputed embedding are available; "
                            "similarity is a discovery signal, not physical evidence."
                        ),
                    ),
                    EvidenceRecord(
                        category="terrain",
                        status=Availability.AVAILABLE
                        if _available_terrain_measurements(candidate.image_id)
                        else Availability.NOT_OBSERVED,
                        summary=_terrain_summary(candidate.image_id),
                        measurements=_terrain_measurements(candidate.image_id),
                    ),
                    EvidenceRecord(
                        category="geology",
                        status=Availability.NOT_OBSERVED,
                        summary=(
                            f"Manifest class is {candidate.label_status}; it is "
                            "not treated as verified geology."
                        ),
                    ),
                ],
            )
        )
    return SearchResponse(
        query_observation_id=query.image_id,
        profile=request.profile,
        method=request.method,
        results=results,
        scope=(
            f"Cross-body {request.method} retrieval over the same "
            f"{len(candidate_indices)}-candidate gallery "
            "in the pilot-100 manifest."
        ),
        terrain_eligible_candidates=len(eligible),
        terrain_excluded_candidates=len(candidate_indices) - len(eligible),
        query_terrain_quality=_terrain_quality(query.image_id),
        limitations=[
            "The pilot manifest labels are provisional and not relevance judgements.",
            (
                f"Terrain scoring requires at least {MIN_TERRAIN_COVERAGE:.0%} observed-cell "
                "coverage and a common measurement at matching physical scales; ineligible "
                "evidence is excluded, not scored as dissimilar."
            ),
            (
                "Combined ranking min-max normalises visual cosine within this gallery and "
                "averages it equally with terrain similarity; it is an exploratory engineering "
                "score, not a scientific calibration."
            ),
            (
                "Terrain similarity uses robustly scaled differences only for same-unit, "
                "scale-matched measurements; absolute planetary elevations are not compared."
            ),
            "Retrieved locations are candidates for review, not validated planetary analogues.",
        ],
    )


@app.get("/api/candidates/{candidate_id}")
def candidate(candidate_id: str) -> dict[str, object]:
    return region(candidate_id)


@app.get("/api/comparisons/{query_id}/{candidate_id}")
def comparison(query_id: str, candidate_id: str) -> dict[str, object]:
    """Return scale-matched measurement differences and explicit evidence gaps."""
    records, indexes, _ = _load()
    if query_id not in indexes or candidate_id not in indexes:
        raise HTTPException(404, detail="Comparison observation is not indexed")
    a, b = records[indexes[query_id]], records[indexes[candidate_id]]
    if a.body == b.body:
        raise HTTPException(422, detail="Comparison requires observations from different bodies")
    query_measurements = _available_terrain_measurements(a.image_id)
    candidate_measurements = _available_terrain_measurements(b.image_id)
    by_name = {measurement.name: measurement for measurement in candidate_measurements}
    terrain_differences: list[dict[str, object]] = []
    for query_measurement in query_measurements:
        candidate_measurement = by_name.get(query_measurement.name)
        if (
            candidate_measurement is None
            or query_measurement.value is None
            or candidate_measurement.value is None
            or query_measurement.spatial_scale_m is None
            or candidate_measurement.spatial_scale_m is None
        ):
            continue
        scale_ratio = max(
            query_measurement.spatial_scale_m, candidate_measurement.spatial_scale_m
        ) / min(query_measurement.spatial_scale_m, candidate_measurement.spatial_scale_m)
        if scale_ratio <= 1.05:
            terrain_differences.append(
                {
                    "name": query_measurement.name,
                    "query_value": query_measurement.value,
                    "candidate_value": candidate_measurement.value,
                    "difference_candidate_minus_query": (
                        candidate_measurement.value - query_measurement.value
                    ),
                    "units": query_measurement.units,
                    "query_scale_m": query_measurement.spatial_scale_m,
                    "candidate_scale_m": candidate_measurement.spatial_scale_m,
                    "scale_match_tolerance": "within 5%",
                    "query_uncertainty_note": query_measurement.uncertainty.description,
                    "candidate_uncertainty_note": candidate_measurement.uncertainty.description,
                }
            )
    data_gaps = [
        "geological mapping",
        "mineralogy",
        "thermal observations",
        "surface material",
        "environmental observations",
    ]
    if not terrain_differences:
        data_gaps.insert(0, "scale-matched terrain measurements")
    elif len(query_measurements) > len(terrain_differences) or len(candidate_measurements) > len(
        terrain_differences
    ):
        data_gaps.insert(0, "additional terrain variables at matching scales")
    return {
        "query": _record_payload(a),
        "candidate": _record_payload(b),
        "supporting_evidence": [
            {
                "category": "visual retrieval",
                "status": "available",
                "summary": (
                    "DINOv2 embedding cosine similarity is available; "
                    "this is not a physical measurement."
                ),
            }
        ],
        "contradictory_evidence": [],
        "terrain_measurement_differences": terrain_differences,
        "data_gaps": data_gaps,
        "limitations": [
            "A lack of indexed evidence is not evidence of physical dissimilarity.",
            "Images differ by sensor, resolution, illumination, and processing.",
            "No scientific analogue validation has been performed for this pair.",
        ],
    }


def _scorecard_sites() -> list[dict[str, Any]]:
    records = {item.image_id: item for item in read_jsonl(MANIFEST)} if MANIFEST.is_file() else {}
    sites: list[dict[str, Any]] = []
    for path in TERRAIN_SIDECARS:
        metadata = json.loads(path.read_text(encoding="utf-8"))
        dataset_id = metadata.get("dataset_id")
        if dataset_id in {"lro-lola-gdr-ldem-64", "lro-lola-gdr-polar-ldem-120m"}:
            body = "moon"
            location = metadata
            polar = dataset_id == "lro-lola-gdr-polar-ldem-120m"
            if polar:
                support = {
                    "status": "partial",
                    "observed_cell_count": metadata.get("observed_cell_count"),
                    "grid_cell_count": metadata.get("grid_cell_count"),
                    "observed_cell_fraction": metadata.get("observed_cell_fraction"),
                    "raster_valid_cell_count": metadata.get("valid_pixel_count"),
                    "note": (
                        "Native cells with zero LDEC direct-shot count are excluded; output cells "
                        "need at least 25% directly sampled support. Counts are not error bars."
                    ),
                }
            else:
                support = {
                    "status": "unknown",
                    "observed_cell_count": None,
                    "grid_cell_count": metadata.get("grid_cell_count"),
                    "observed_cell_fraction": None,
                    "raster_valid_cell_count": metadata.get("valid_pixel_count"),
                    "note": "Direct-shot coverage is not quantified by the LOLA GDR product.",
                }
            quality = str(
                metadata.get(
                    "uncertainty_note", "LOLA polar direct-shot coverage is not quantified."
                )
            )
        elif dataset_id == "mola-meg128":
            body = "mars"
            record = records.get(str(metadata.get("observation_id", "")))
            if record is None:
                continue
            location = {
                "name": record.geographic_group.replace("_", " "),
                "longitude_east_deg": record.longitude,
                "latitude_deg": record.latitude,
            }
            support = {
                "status": "partial",
                "observed_cell_count": metadata.get("observed_cell_count"),
                "grid_cell_count": metadata.get("grid_cell_count"),
                "observed_cell_fraction": metadata.get("observed_cell_fraction"),
                "raster_valid_cell_count": None,
                "note": (
                    "Zero-count MOLA bins are excluded; the observed-only regional range "
                    "may miss unsampled extrema."
                ),
            }
            quality = str(
                metadata.get("missing_data_semantics", "MOLA observed-bin coverage is incomplete.")
            )
        else:
            continue
        sites.append(
            metadata
            | {
                "body": body,
                "name": location.get("name", str(metadata.get("observation_id", ""))),
                "longitude_east_deg": location.get("longitude_east_deg"),
                "latitude_deg": location.get("latitude_deg"),
                "data_coverage": support,
                "uncertainty_note": quality,
                "label_url": metadata.get("label_url")
                or (
                    str(metadata["source_url"]).removesuffix(".img") + ".xml"
                    if dataset_id == "mola-meg128"
                    else metadata.get("dataset_reference_url")
                ),
            }
        )
    return sorted(sites, key=lambda item: str(item.get("observation_id", "")))


def _environmental_evidence_for(observation_id: str) -> dict[str, object] | None:
    """Return optional non-terrain evidence without treating it as score input."""
    for path in sorted((ROOT / "data/terrain").glob("*.tif.json")):
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if metadata.get("observation_id") == observation_id and str(
            metadata.get("scorecard_role", "")
        ).startswith("environmental_evidence_only"):
            measurement = metadata.get("measurement", {})
            raw_summary = measurement.get("summary", {}) if isinstance(measurement, dict) else {}
            summary = {
                "mean": raw_summary.get("mean", raw_summary.get("mean_k")),
                "median": raw_summary.get("median", raw_summary.get("median_k")),
                "p10": raw_summary.get("p10", raw_summary.get("p10_k")),
                "p90": raw_summary.get("p90", raw_summary.get("p90_k")),
            }
            return {
                "body": metadata.get("body"),
                "dataset_id": metadata.get("dataset_id"),
                "product_id": metadata.get("source_product_id"),
                "source_url": metadata.get("source_url"),
                "label_url": metadata.get("label_url"),
                "mask_url": metadata.get("mask_url"),
                "retrieved_at": metadata.get("retrieved_at"),
                "measurement": measurement,
                "summary": summary,
                "valid_sample_fraction": metadata.get("valid_sample_fraction"),
                "sample_count": metadata.get("sample_count"),
                "valid_sample_count": metadata.get("valid_sample_count"),
                "context_size_m": metadata.get("context_size_m"),
                "product_start_time": metadata.get("product_start_time"),
                "product_stop_time": metadata.get("product_stop_time"),
                "source_description": metadata.get("source_description"),
                "earth_comparison_status": metadata.get("earth_comparison_status"),
                "scorecard_role": metadata.get("scorecard_role"),
                "units": metadata.get("units"),
                "observation_period": metadata.get("observation_period"),
            }
    return None


@lru_cache(maxsize=1)
def _mars_geology_records() -> list[dict[str, object]]:
    """Load cached point classifications from the USGS global Mars map."""
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((ROOT / "data/geology").glob("usgs-sim1083-*.json"))
    ] + [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((ROOT / "data/geology").glob("usgs-candidate-mars-*.json"))
    ]


@lru_cache(maxsize=1)
def _lunar_geology_records() -> list[dict[str, object]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for pattern in ("usgs-unified-moon-*.json", "usgs-candidate-moon-*.json")
        for path in sorted((ROOT / "data/geology").glob(pattern))
    ]


@lru_cache(maxsize=1)
def _earth_geology_records(mapped_only: bool = False) -> list[dict[str, object]]:
    rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((ROOT / "data/geology").glob("usgs-candidate-earth-*.json"))
    ]
    if mapped_only:
        return [
            row
            for row in rows
            if row.get("classification_status") in {"mapped", "boundary_ambiguous"}
        ]
    return rows


def _geology_evidence_for(observation_id: str) -> dict[str, object] | None:
    """Return categorical lunar or Mars map context, never a score feature."""
    records = _mars_geology_records() + _lunar_geology_records()
    for metadata in records:
        if metadata.get("observation_id") == observation_id:
            return {
                "dataset_id": metadata.get("dataset_id"),
                "product_id": metadata.get("source_product_id"),
                "source_url": metadata.get("source_url"),
                "dataset_reference_url": metadata.get("dataset_reference_url"),
                "retrieved_at": metadata.get("retrieved_at"),
                "map_unit_code": metadata.get("map_unit_code"),
                "map_unit_name": metadata.get("map_unit_name"),
                "map_unit_age": metadata.get("map_unit_age"),
                "map_unit_description": metadata.get("map_unit_description"),
                "map_unit_interpretation": metadata.get("map_unit_interpretation"),
                "candidate_unit_codes": metadata.get("candidate_unit_codes", []),
                "classification_status": metadata.get("classification_status"),
                "nominal_cartographic_scale": metadata.get("nominal_cartographic_scale"),
                "source_description": metadata.get("source_description"),
                "usage_note": metadata.get("usage_note"),
                "scorecard_role": metadata.get("scorecard_role"),
            }
    return None


@app.get("/api/scorecards/sites")
def scorecard_sites() -> dict[str, object]:
    """List ingested NASA Moon/Mars reference sites and their data coverage."""
    sites = _scorecard_sites()
    return {
        "status": "available" if sites else "not_observed",
        "sites": [
            {
                "id": site["observation_id"],
                "name": site["name"],
                "body": site["body"],
                "longitude_east_deg": site["longitude_east_deg"],
                "latitude_deg": site["latitude_deg"],
                "dataset_id": site["dataset_id"],
                "source_product_id": site["source_product_id"],
                "source_url": site["source_url"],
                "retrieved_at": site.get("retrieved_at"),
                "measurements": site["measurements"],
                "environmental_evidence": _environmental_evidence_for(site["observation_id"]),
                "geology_evidence": _geology_evidence_for(site["observation_id"]),
                "data_quality": site["uncertainty_note"],
                "data_coverage": site["data_coverage"],
                "counts_source_url": site.get("counts_source_url"),
            }
            for site in sites
        ],
        "message": None
        if sites
        else "No NASA lunar or Mars terrain scorecard observations are indexed.",
    }


@app.get("/api/scorecards/config")
def scorecard_config() -> dict[str, object]:
    """Expose terrain variables, research weights, and scorecard interpretation."""
    return {
        "variables": {
            key: {
                "label": value["label"],
                "units": value["units"],
                "tolerance": value["tolerance"],
            }
            for key, value in VARIABLES.items()
        },
        "mission_objectives": MISSION_PRESETS,
        "weight_semantics": (
            "Non-negative weights are normalized across compatible measurements. "
            "All-zero weights are invalid."
        ),
    }


@app.post("/api/scorecards/rank")
def rank_scorecard(request: ScorecardRequest) -> dict[str, object]:
    """Rank Earth contexts against a NASA reference using available matched data."""
    try:
        weights = validate_weights(request.weights)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    reference = next(
        (site for site in _scorecard_sites() if site.get("observation_id") == request.site_id), None
    )
    if reference is None:
        raise HTTPException(
            404,
            detail={
                "code": "scorecard_site_not_found",
                "message": "No ingested NASA lunar or Mars terrain observation has this ID",
            },
        )
    candidates = _rank_earth_contexts(reference.get("measurements", []), weights, request.limit)
    return {
        "site": _scorecard_reference_payload(reference, request.mission_objective),
        "mission_objective": request.mission_objective,
        "mission_objective_name": MISSION_PRESETS[request.mission_objective]["name"],
        "weights": weights,
        "ranking_method": (
            "Weighted mean of exp(-absolute difference / variable tolerance), normalized "
            "across available same-unit variables at matching scales."
        ),
        "candidates": candidates[: request.limit],
        "candidate_coverage": {
            "indexed_earth_dem_contexts": len(candidates),
            "dataset_ids": sorted({str(item["source"]["dataset_id"]) for item in candidates}),
            "status": "partial_catalogue",
            "note": (
                "Ranks only Earth DEM product contexts ingested here; this is not global search "
                "or a new-analogue determination."
            ),
        },
        "limitations": [
            "Terrain similarity is not probability, analogue validation, or site suitability.",
            (
                "LOLA LDEM_64 is a gridded shape/radius product; interpolation was used, "
                "and direct-observation coverage is not quantified in this crop."
            ),
            (
                "MOLA MEG128 comparison uses observed-bin elevation range over the 10.19 km "
                "footprint as a regional-relief proxy; it does not estimate slope or roughness, "
                "and sparse count-grid support can miss local extrema."
            ),
            (
                "Copernicus GLO-30 is a surface model with different acquisition and "
                "processing characteristics."
            ),
            (
                "Contexts are resampled to 463.06 m cells over about 10.19 km, but "
                "scales and uncertainties still differ."
            ),
            (
                "Mission thresholds are provisional research-screening assumptions "
                "documented in the methodology; they are not validated against a specific "
                "vehicle or engineering design."
            ),
            (
                "A Moon-only Diviner nighttime regolith-temperature context is exposed where "
                "available but is not paired with Earth thermal data or scored. Mars sites "
                "also expose generalized USGS map-unit codes; these are not local material "
                "measurements. Mineralogy, radiation, illumination, and volatiles are not included."
            ),
        ],
    }


def _rank_earth_contexts(
    reference_measurements: list[dict[str, Any]],
    weights: dict[str, float],
    limit: int,
) -> list[dict[str, Any]]:
    """Score and order ingested Earth DEM contexts for one NASA reference."""
    # Scientific scorecards do not depend on the optional visual embedding matrix.
    records = read_jsonl(MANIFEST) if MANIFEST.is_file() else []
    record_by_id = {record.image_id: record for record in records}
    candidates: list[dict[str, Any]] = []
    for earth in TERRAIN_SIDECARS:
        metadata = json.loads(earth.read_text(encoding="utf-8"))
        dataset_id = metadata.get("dataset_id")
        if dataset_id not in {"cop-dem-glo-30", "nasadem-hgt"}:
            continue
        observation_id = str(metadata.get("observation_id", ""))
        record = record_by_id.get(observation_id)
        if record is None:
            continue
        result = compare_candidate(
            reference_measurements, metadata.get("measurements", []), weights
        )
        weighted_matches = [
            item
            for item in result["variables"]
            if item.get("score") is not None and float(item["weight"]) > 0
        ]
        explanation = sorted(
            weighted_matches,
            key=lambda item: (-float(item["weight"]) * float(item["score"]), item["name"]),
        )[:2]
        candidates.append(
            {
                "observation_id": (
                    observation_id
                    if dataset_id == "cop-dem-glo-30"
                    else f"nasadem:{observation_id}"
                ),
                "name": (
                    f"{record.geographic_group.replace('_', ' ')} · "
                    f"{'Copernicus GLO-30' if dataset_id == 'cop-dem-glo-30' else 'NASADEM'}"
                ),
                "longitude_east_deg": record.longitude,
                "latitude_deg": record.latitude,
                "similarity_score": result["similarity_score"],
                "score_interpretation": result["score_interpretation"],
                "data_completeness": result["data_completeness"],
                "matched_variable_count": result["matched_variable_count"],
                "requested_variable_count": result["requested_variable_count"],
                "variables": result["variables"],
                "why_ranked": [
                    f"{item['label']} matched with a normalized score of {float(item['score']):.3f}"
                    for item in explanation
                ],
                "mission_suitability": {
                    "status": "not_assessed",
                    "checks": [],
                    "qualification": (
                        "Earth candidate suitability as an analogue field/test site needs "
                        "separate access, safety, process-specific and engineering criteria; "
                        "terrain similarity does not assess it."
                    ),
                },
                "source": {
                    "dataset_id": dataset_id,
                    "product_id": metadata.get("source_product_id"),
                    "url": metadata.get("source_url"),
                    "documentation_url": metadata.get("dataset_reference_url")
                    or metadata.get("source_catalog_url"),
                    "retrieved_at": metadata.get("retrieved_at"),
                    "processing_method": metadata.get("processing_method"),
                    "data_coverage": metadata.get("data_coverage"),
                    "direct_srtm_source_fraction": metadata.get("direct_srtm_class_fraction"),
                },
            }
        )
    candidates.sort(
        key=lambda item: (
            item["similarity_score"] is None,
            -(float(item["similarity_score"]) if item["similarity_score"] is not None else 0.0),
            str(item["observation_id"]),
        )
    )
    for rank, candidate in enumerate(candidates[:limit], 1):
        candidate["rank"] = rank
    return candidates


def _scorecard_reference_payload(
    reference: dict[str, Any], mission_objective: str
) -> dict[str, object]:
    """Combine NASA reference measurements with provenance and screening results."""
    observation_id = str(reference["observation_id"])
    measurements = reference.get("measurements", [])
    return {
        "id": observation_id,
        "name": reference["name"],
        "body": reference["body"],
        "longitude_east_deg": reference["longitude_east_deg"],
        "latitude_deg": reference["latitude_deg"],
        "measurements": measurements,
        "environmental_evidence": _environmental_evidence_for(observation_id),
        "geology_evidence": _geology_evidence_for(observation_id),
        "data_quality": reference.get("uncertainty_note"),
        "data_coverage": reference["data_coverage"],
        "source": {
            "dataset_id": reference.get("dataset_id"),
            "product_id": reference.get("source_product_id"),
            "url": reference.get("source_url"),
            "support_url": reference.get("counts_source_url"),
            "label_url": reference.get("label_url"),
            "retrieved_at": reference.get("retrieved_at"),
            "observation_period": reference.get("observation_period"),
        },
        "mission_suitability": mission_suitability(measurements, mission_objective),
    }


# The discovery index is built explicitly offline; requests never build it.
DISCOVERY_INDEX = Path(
    os.getenv("ENOM_DISCOVERY_INDEX", str(ROOT / "artifacts/discovery/index.sqlite"))
)


class DiscoveryCoordinateRequest(BaseModel):
    body: Literal["moon", "mars"]
    latitude_deg: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitude_east_deg: float = Field(allow_inf_nan=False)


class DiscoveryRankRequest(BaseModel):
    index_id: str
    context_id: str
    weights: dict[str, float]
    dimension_weights: dict[str, float] = Field(default_factory=dict)
    land_cover_min_fractions: dict[str, float] = Field(default_factory=dict)
    land_cover_max_fractions: dict[str, float] = Field(default_factory=dict)
    result_limit: int = Field(default=10, ge=1, le=100)
    result_offset: int = Field(default=0, ge=0)

    @field_validator("weights", mode="before")
    @classmethod
    def numeric_weights(cls, value: object) -> object:
        if not isinstance(value, dict) or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) for v in value.values()
        ):
            raise ValueError("weights must be numeric")
        return value

    @field_validator("land_cover_max_fractions", mode="before")
    @classmethod
    def numeric_land_cover_filters(cls, value: object) -> object:
        if not isinstance(value, dict) or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) for v in value.values()
        ):
            raise ValueError("land-cover maximum fractions must be numeric")
        return value

    @field_validator("land_cover_min_fractions", mode="before")
    @classmethod
    def numeric_land_cover_min_filters(cls, value: object) -> object:
        if not isinstance(value, dict) or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) for v in value.values()
        ):
            raise ValueError("land-cover minimum fractions must be numeric")
        return value

    @field_validator("dimension_weights", mode="before")
    @classmethod
    def numeric_dimension_weights(cls, value: object) -> object:
        if not isinstance(value, dict) or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) for v in value.values()
        ):
            raise ValueError("dimension_weights must be numeric")
        if value:
            analogue.validate_dimension_weights(value)
        return value


class DiscoveryIndexResponse(BaseModel):
    index_id: str
    policy_version: str
    policy_hash: str
    scoring_method: str
    policy: dict[str, Any]
    counts: dict[str, int]
    variables: dict[str, Any]
    presets: dict[str, Any]


class DiscoveryCoverageResponse(BaseModel):
    index_id: str
    contexts: list[dict[str, Any]]


class DiscoveryResolveResponse(DiscoveryCoverageResponse):
    click: DiscoveryCoordinateRequest
    status: Literal["covered", "out_of_coverage"]
    coordinate_frame: str


class DiscoveryComparison(BaseModel):
    context: dict[str, Any]
    evidence_class: Literal["multi_feature", "limited_evidence"]
    terrain_support_class: Literal["multi_feature", "limited_evidence"]
    similarity_score: float | None
    score_interpretation: str
    data_completeness: float
    matched_variable_count: int
    requested_variable_count: int
    variables: list[dict[str, Any]]
    score: float | None = None
    evidence_coverage: float | None = None
    dimension_scores: list[dict[str, Any]] = Field(default_factory=list)
    missing_dimensions: list[str] = Field(default_factory=list)
    dimension_evidence_class: str | None = None
    independent_evidence_group_count: int = 0
    contributing_dimension_count: int = 0
    rank: int


class DiscoveryRankResponse(BaseModel):
    index_id: str
    policy_version: str
    policy_hash: str
    scoring_method: str
    weights: dict[str, float]
    dimension_weights: dict[str, float]
    ranking_tie_tolerance: float
    near_equivalent_count: int
    near_equivalent_context_ids: list[str]
    near_equivalent_ids_truncated: bool
    applied_land_cover_filters: dict[str, float]
    applied_land_cover_min_fractions: dict[str, float]
    land_cover_filter_excluded_count: int
    land_cover_missing_count: int
    land_cover_unsuitable_count: int
    target: dict[str, Any]
    status: Literal["ranked", "insufficient_evidence"]
    results: list[DiscoveryComparison]
    total_results: int
    result_limit: int
    result_offset: int
    next_result_offset: int | None
    recommendations: list[DiscoveryComparison]
    diversified_count: int
    suppressed_neighbours: int
    mission_suitability: dict[str, str]
    limitations: list[str]


def _discovery_index() -> Path:
    import sqlite3

    if not DISCOVERY_INDEX.is_file():
        raise HTTPException(503, detail="Discovery index unavailable; build it offline first")
    try:
        with sqlite3.connect(f"file:{DISCOVERY_INDEX.resolve()}?mode=ro", uri=True) as database:
            version = database.execute("SELECT schema_version FROM release").fetchone()
            if version != (4,):
                raise sqlite3.DatabaseError("unsupported index version")
            for table in (
                "contexts",
                "places",
                "context_places",
                "context_quality",
                "measurements",
                "source_products",
                "bounds_index",
            ):
                database.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
    except sqlite3.Error as exc:
        raise HTTPException(503, detail="Discovery index is invalid or incompatible") from exc
    return DISCOVERY_INDEX


@app.get("/api/discovery/index", response_model=DiscoveryIndexResponse)
def discovery_index_info() -> dict[str, object]:
    from twinworld.discovery import POLICY, POLICY_HASH, POLICY_VERSION, SCORING_METHOD, read_index

    index_id, contexts = read_index(_discovery_index())
    return {
        "index_id": index_id,
        "policy_version": POLICY_VERSION,
        "policy_hash": POLICY_HASH,
        "scoring_method": SCORING_METHOD,
        "policy": POLICY,
        "counts": {
            body: sum(c["index_body"] == body for c in contexts)
            for body in ("earth", "moon", "mars")
        },
        "variables": VARIABLES,
        "presets": MISSION_PRESETS,
    }


@app.get("/api/discovery/coverage", response_model=DiscoveryCoverageResponse)
def discovery_coverage(body: Literal["moon", "mars"]) -> dict[str, object]:
    from twinworld.discovery import (
        _footprint_compatible,
        _support_ok,
        comparison_measurements,
        read_index,
    )
    from twinworld.scorecards import measurements_by_name

    index_id, contexts = read_index(_discovery_index())
    earth = [c for c in contexts if c["index_body"] == "earth" and _support_ok(c)]
    targets = []
    for context in contexts:
        if context["index_body"] != body:
            continue
        measurements = comparison_measurements(context)
        eligible = bool(measurements_by_name(measurements)) and _support_ok(context)
        eligible = eligible and any(
            _footprint_compatible(context, candidate)
            and compare_candidate(
                measurements, comparison_measurements(candidate), {name: 1.0 for name in VARIABLES}
            )["similarity_score"]
            is not None
            for candidate in earth
        )
        targets.append({**context, "eligible_for_ranking": eligible})
    return {"index_id": index_id, "contexts": targets}


@app.get("/api/discovery/contexts/{context_id}")
def discovery_context_detail(context_id: str) -> dict[str, Any]:
    """Load complete evidence for one chosen context, separate from rank pages."""
    from twinworld.discovery import _dimension_inputs, read_index
    from twinworld.scientific_observations import local_observation_catalogue

    index_id, contexts = read_index(_discovery_index())
    context = next((row for row in contexts if row["observation_id"] == context_id), None)
    if context is None:
        raise HTTPException(404, detail="Discovery context not found")
    return {
        "index_id": index_id,
        "context": context,
        "dimensions": _dimension_inputs(context, local_observation_catalogue(ROOT)),
    }


@app.post("/api/discovery/resolve", response_model=DiscoveryResolveResponse)
def discovery_resolve(request: DiscoveryCoordinateRequest) -> dict[str, object]:
    from twinworld.discovery import read_index
    from twinworld.feature_index import resolve

    path = _discovery_index()
    index_id, _ = read_index(path)
    matches = resolve(path, request.body, request.latitude_deg, request.longitude_east_deg)
    return {
        "index_id": index_id,
        "click": request.model_dump(),
        "status": "covered" if matches else "out_of_coverage",
        "coordinate_frame": (
            "Moon: east-positive planetocentric coordinates interpreted in the LOLA "
            "mean-Earth/polar-axis frame; basemap alignment is not independently verified."
            if request.body == "moon"
            else "Mars: east-positive planetocentric coordinates in the indexed MOLA frame."
        ),
        "contexts": matches,
    }


@app.post("/api/discovery/rank", response_model=DiscoveryRankResponse)
def discovery_rank(request: DiscoveryRankRequest) -> dict[str, object]:
    from twinworld.discovery import rank

    try:
        return rank(
            _discovery_index(),
            request.index_id,
            request.context_id,
            request.weights,
            dimension_weights=request.dimension_weights,
            land_cover_max_fractions=request.land_cover_max_fractions,
            land_cover_min_fractions=request.land_cover_min_fractions,
            result_limit=request.result_limit,
            result_offset=request.result_offset,
        )
    except KeyError as exc:
        raise HTTPException(404, detail="Discovery context not found") from exc
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, detail=str(exc)) from exc

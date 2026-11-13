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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field

from twinworld.records import PatchRecord, read_jsonl
from twinworld.retrieval import normalize_rows
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


class SearchRequest(BaseModel):
    observation_id: str
    profile: Literal["aeolian", "rover_mobility", "ancient_water", "volcanic"] = "aeolian"
    method: Literal["visual", "terrain", "combined"] = "visual"
    limit: int = Field(default=10, ge=1, le=50)


class SearchResult(BaseModel):
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
    site_id: str
    mission_objective: Literal["landing", "base_construction", "rover_mobility"]
    weights: dict[str, float]
    limit: int = Field(default=20, ge=1, le=100)


@lru_cache(maxsize=1)
def _load() -> tuple[list[PatchRecord], dict[str, int], np.ndarray]:
    if not MANIFEST.is_file() or not EMBEDDINGS.is_file():
        return [], {}, np.empty((0, 0), dtype=np.float32)
    records = read_jsonl(MANIFEST)
    matrix = np.load(EMBEDDINGS, allow_pickle=False)
    metadata_path = EMBEDDINGS.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("image_ids") != [record.image_id for record in records]:
        raise RuntimeError("DINOv2 embedding IDs do not match the manifest order")
    if matrix.ndim != 2 or matrix.shape[0] != len(records):
        raise RuntimeError("DINOv2 embedding matrix does not match the manifest")
    if matrix.shape[1] != metadata.get("embedding_dimension"):
        raise RuntimeError("DINOv2 embedding dimension does not match artifact metadata")
    if not np.isfinite(matrix).all():
        raise RuntimeError("DINOv2 embedding matrix contains non-finite values")
    return records, {record.image_id: index for index, record in enumerate(records)}, matrix


def _record_payload(record: PatchRecord) -> dict[str, object]:
    measurements = _terrain_measurements(record.image_id)
    terrain_records = _terrain_records(record.image_id)
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
        + (["terrain_dem"] if measurements else []),
        "unavailable_evidence": [
            name
            for name in ("terrain_dem", "geology", "mineralogy", "thermal")
            if not (name == "terrain_dem" and measurements)
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
                    "native_resolution_m_at_equator",
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
    for measurement in _terrain_measurements(observation_id):
        if measurement.value is not None and measurement.spatial_scale_m is not None:
            vector[measurement.name] = (
                float(measurement.value),
                float(measurement.spatial_scale_m),
                measurement.units,
            )
    return vector


def _terrain_similarity(query_id: str, candidate_id: str, all_ids: list[str]) -> float | None:
    query, candidate = _terrain_vector(query_id), _terrain_vector(candidate_id)
    common = sorted(set(query) & set(candidate))
    if not common:
        return None
    distances = []
    for name in common:
        q_value, q_scale, q_units = query[name]
        c_value, c_scale, c_units = candidate[name]
        if q_units != c_units or max(q_scale, c_scale) / min(q_scale, c_scale) > 1.05:
            continue
        values = [
            _terrain_vector(item)[name][0] for item in all_ids if name in _terrain_vector(item)
        ]
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
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, object]:
    records, _, matrix = _load()
    return {"status": "ok", "records": len(records), "visual_index": bool(matrix.size)}


@app.get("/api/planets")
def planets() -> list[dict[str, object]]:
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
                "Outside footprint or nodata; current coverage is one 10.2 km Namib context "
                "around a 2 km image crop"
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
                "One bounded 22×22 cell scorecard crop; direct-shot coverage is not quantified"
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
    ]


@app.get("/api/datasets/{dataset_id}/coverage")
def dataset_coverage(dataset_id: str) -> dict[str, object]:
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
    records, _, _ = _load()
    return [_record_payload(r) for r in records if body is None or r.body == body][
        : max(1, min(limit, 500))
    ]


@app.get("/api/regions/{observation_id}")
def region(observation_id: str) -> dict[str, object]:
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
    matrix = normalize_rows(vectors)
    candidate_indices = [i for i, record in enumerate(records) if record.body != query.body]
    scores = matrix[candidate_indices] @ matrix[query_index]
    visual_order = np.argsort(-scores, kind="stable")
    visual_ranks = {candidate_indices[int(pos)]: rank for rank, pos in enumerate(visual_order, 1)}
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
    score_by_index = {index: float(scores[pos]) for pos, index in enumerate(candidate_indices)}
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
                        if _terrain_measurements(candidate.image_id)
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
    records, indexes, _ = _load()
    if query_id not in indexes or candidate_id not in indexes:
        raise HTTPException(404, detail="Comparison observation is not indexed")
    a, b = records[indexes[query_id]], records[indexes[candidate_id]]
    if a.body == b.body:
        raise HTTPException(422, detail="Comparison requires observations from different bodies")
    query_measurements = _terrain_measurements(a.image_id)
    candidate_measurements = _terrain_measurements(b.image_id)
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
    sites = []
    for path in TERRAIN_SIDECARS:
        metadata = json.loads(path.read_text(encoding="utf-8"))
        if metadata.get("body") == "moon" and metadata.get("dataset_id") == "lro-lola-gdr-ldem-64":
            sites.append(metadata)
    return sorted(sites, key=lambda item: str(item.get("observation_id", "")))


@app.get("/api/scorecards/sites")
def scorecard_sites() -> dict[str, object]:
    sites = _scorecard_sites()
    return {
        "status": "available" if sites else "not_observed",
        "sites": [
            {
                "id": site["observation_id"],
                "name": site["name"],
                "body": "moon",
                "longitude_east_deg": site["longitude_east_deg"],
                "latitude_deg": site["latitude_deg"],
                "dataset_id": site["dataset_id"],
                "source_product_id": site["source_product_id"],
                "source_url": site["source_url"],
                "retrieved_at": site["retrieved_at"],
                "measurements": site["measurements"],
                "data_quality": site["uncertainty_note"],
            }
            for site in sites
        ],
        "message": None
        if sites
        else "No LOLA lunar terrain crop is ingested. Run scripts/ingest_lola_scorecard.py.",
    }


@app.get("/api/scorecards/config")
def scorecard_config() -> dict[str, object]:
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
    try:
        weights = validate_weights(request.weights)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    lunar = next(
        (site for site in _scorecard_sites() if site.get("observation_id") == request.site_id), None
    )
    if lunar is None:
        raise HTTPException(
            404,
            detail={
                "code": "scorecard_site_not_found",
                "message": "No ingested LOLA scorecard site has this ID",
            },
        )
    # Scientific scorecards do not depend on the optional visual embedding matrix.
    records = read_jsonl(MANIFEST) if MANIFEST.is_file() else []
    record_by_id = {record.image_id: record for record in records}
    candidates = []
    for earth in TERRAIN_SIDECARS:
        metadata = json.loads(earth.read_text(encoding="utf-8"))
        if metadata.get("dataset_id") != "cop-dem-glo-30":
            continue
        observation_id = str(metadata.get("observation_id", ""))
        record = record_by_id.get(observation_id)
        if record is None:
            continue
        result = compare_candidate(
            lunar.get("measurements", []), metadata.get("measurements", []), weights
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
                "observation_id": observation_id,
                "name": record.geographic_group.replace("_", " "),
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
                    "dataset_id": metadata.get("dataset_id"),
                    "product_id": metadata.get("source_product_id"),
                    "url": metadata.get("source_url"),
                    "retrieved_at": metadata.get("retrieved_at"),
                    "processing_method": metadata.get("processing_method"),
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
    for rank, candidate in enumerate(candidates[: request.limit], 1):
        candidate["rank"] = rank
    return {
        "site": {
            "id": lunar["observation_id"],
            "name": lunar["name"],
            "body": "moon",
            "longitude_east_deg": lunar["longitude_east_deg"],
            "latitude_deg": lunar["latitude_deg"],
            "measurements": lunar.get("measurements", []),
            "data_quality": lunar.get("uncertainty_note"),
            "source": {
                "dataset_id": lunar.get("dataset_id"),
                "product_id": lunar.get("source_product_id"),
                "url": lunar.get("source_url"),
                "label_url": lunar.get("label_url"),
                "retrieved_at": lunar.get("retrieved_at"),
                "observation_period": lunar.get("observation_period"),
            },
            "mission_suitability": mission_suitability(
                lunar.get("measurements", []), request.mission_objective
            ),
        },
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
            "dataset_id": "cop-dem-glo-30",
            "status": "partial_catalogue",
            "note": (
                "Ranks only Earth DEM contexts ingested here; this is not global search "
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
                "Geology, thermal environment, radiation, illumination, and volatiles "
                "are not included."
            ),
        ],
    }

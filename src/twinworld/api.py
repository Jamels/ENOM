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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field

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
    expected_space_id = (
        f"{metadata['model_id']}@{metadata['revision']}:{preprocessing_id}"
    )
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
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, object]:
    """Report API readiness and whether the local visual index is available."""
    records, _, matrix = _load()
    return {"status": "ok", "records": len(records), "visual_index": bool(matrix.size)}


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
            "status": "operational"
            if list((ROOT / "data/geology").glob("usgs-unified-moon-*.json"))
            else "registered",
            "coverage_count": len(list((ROOT / "data/geology").glob("usgs-unified-moon-*.json"))),
        },
    ]


@app.get("/api/datasets/{dataset_id}/coverage")
def dataset_coverage(dataset_id: str) -> dict[str, object]:
    """Describe indexed coverage and the dataset's observation-level limits."""
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
    visual_ranks = {
        index: rank for rank, (index, _) in enumerate(visual_results, start=1)
    }
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
        if dataset_id == "lro-lola-gdr-ldem-64":
            body = "moon"
            location = metadata
            support = {
                "status": "unknown",
                "observed_cell_count": None,
                "grid_cell_count": metadata.get("grid_cell_count"),
                "observed_cell_fraction": None,
                "raster_valid_cell_count": metadata.get("valid_pixel_count"),
                "note": "Direct-shot coverage is not quantified by the LOLA GDR product.",
            }
            quality = str(
                metadata.get("uncertainty_note", "LOLA direct-shot coverage is not quantified.")
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
    ]


def _geology_evidence_for(observation_id: str) -> dict[str, object] | None:
    """Return categorical lunar or Mars map context, never a score feature."""
    records = _mars_geology_records() + [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((ROOT / "data/geology").glob("usgs-unified-moon-*.json"))
    ]
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

#!/usr/bin/env python3
"""Run cross-planet retrieval on the 100-patch pilot with a pinned DINOv2 profile."""

# ruff: noqa: I001

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import tempfile
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_annotation_gallery import _preview_data_uri  # noqa: E402
from pilot_benchmark_report import render_report  # noqa: E402

import build_pilot as pilot  # noqa: E402
from twinworld.evaluation import precision_at_k, random_ranking  # noqa: E402
from twinworld.features import classical_descriptor  # noqa: E402
from twinworld.patching import extract_metric_patch  # noqa: E402
from twinworld.records import (  # noqa: E402
    Body,
    Landform,
    PatchRecord,
    read_jsonl,
    validate_records,
)
from twinworld.retrieval import normalize_rows, search  # noqa: E402
from twinworld.spatial import ensure_no_overlaps  # noqa: E402
from twinworld.vision import embed_dinov2, file_sha256  # noqa: E402

MANIFEST = ROOT / "data/manifests/pilot-100.jsonl"
ANNOTATIONS = ROOT / "data/annotations/pilot-100.csv"
ARTIFACT_DIR = ROOT / "artifacts/pilot-100"
REPORT = ROOT / "reports/pilot-evaluation.html"
PLAN = ROOT / "data/manifests/pilot-plan.json"
PATCH_TIMING_CACHE = ARTIFACT_DIR / "patch-processing-sample.json"
MODEL_CONFIG = yaml.safe_load((ROOT / "configs/models.yaml").read_text(encoding="utf-8"))
LABELS: tuple[Landform, ...] = (
    "barchan_crescent_dune",
    "linear_dune",
    "other_dune",
    "rocky_ridge_layered",
    "other_non_dune",
)


def _annotations(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as source:
        return {row["image_id"]: row for row in csv.DictReader(source)}


def _evaluation_labels(
    records: list[PatchRecord], annotations: dict[str, dict[str, str]]
) -> tuple[list[PatchRecord], str]:
    fully_reviewed = all(
        annotations.get(record.image_id, {}).get("review_status") == "reviewed"
        and annotations.get(record.image_id, {}).get("reviewed_label") in LABELS
        for record in records
    )
    field = "reviewed_label" if fully_reviewed else "proposed_label"
    labeled = []
    for record in records:
        label = annotations.get(record.image_id, {}).get(field, "")
        if label not in LABELS:
            raise ValueError(f"missing valid {field} for {record.image_id}")
        labeled.append(replace(record, label=cast(Landform, label)))
    return labeled, "independently reviewed" if fully_reviewed else "provisional proposed labels"


def _classical_features(records: list[PatchRecord]) -> tuple[np.ndarray, bool]:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    cache = ARTIFACT_DIR / "embeddings_hog_lbp.npy"
    meta = ARTIFACT_DIR / "embeddings_hog_lbp.json"
    ids = [record.image_id for record in records]
    checksums = [file_sha256(ROOT / record.path) for record in records]
    if cache.is_file() and meta.is_file():
        info = json.loads(meta.read_text(encoding="utf-8"))
        if info.get("image_ids") == ids and info.get("source_sha256") == checksums:
            matrix = np.load(cache, allow_pickle=False)
            if matrix.shape[0] == len(records) and np.isfinite(matrix).all():
                return matrix, True
    matrix = np.stack([classical_descriptor(ROOT / record.path) for record in records])
    matrix = normalize_rows(matrix)
    np.save(cache, matrix, allow_pickle=False)
    meta.write_text(
        json.dumps(
            {
                "image_ids": ids,
                "source_sha256": checksums,
                "descriptor": "HOG+uniform-LBP",
                "normalized": True,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return matrix, False


def _method_results(
    name: str, matrix: np.ndarray, records: list[PatchRecord], basis: str
) -> dict[str, Any]:
    matrix = normalize_rows(matrix)
    query_results: dict[str, Any] = {}
    values: dict[str, list[float]] = {
        "earth_to_mars_p1": [],
        "earth_to_mars_p5": [],
        "mars_to_earth_p1": [],
        "mars_to_earth_p5": [],
    }
    for query_index, query in enumerate(records):
        results = search(matrix, records, query_index, top_k=5)
        ranked_ids = [records[index].image_id for index, _ in results]
        relevant = {
            record.image_id
            for record in records
            if record.body != query.body and record.label == query.label
        }
        direction = f"{query.body}_to_{'mars' if query.body == 'earth' else 'earth'}"
        p1 = precision_at_k(ranked_ids, relevant, 1)
        p5 = precision_at_k(ranked_ids, relevant, min(5, len(ranked_ids)))
        values[f"{direction}_p1"].append(p1)
        values[f"{direction}_p5"].append(p5)
        query_results[query.image_id] = [
            {"image_id": records[index].image_id, "score": score} for index, score in results
        ]
    metrics = {key: float(np.mean(scores)) for key, scores in values.items()}
    metrics["macro_p1"] = float(np.mean([metrics["earth_to_mars_p1"], metrics["mars_to_earth_p1"]]))
    metrics["macro_p5"] = float(np.mean([metrics["earth_to_mars_p5"], metrics["mars_to_earth_p5"]]))
    return {
        "method": name,
        "evaluation_basis": basis,
        "metrics": metrics,
        "rankings": query_results,
    }


def _random_results(records: list[PatchRecord], basis: str, seed: int) -> dict[str, Any]:
    results: dict[str, Any] = {}
    metrics: dict[str, list[float]] = {
        "earth_to_mars_p1": [],
        "earth_to_mars_p5": [],
        "mars_to_earth_p1": [],
        "mars_to_earth_p5": [],
    }

    for query_index, query in enumerate(records):
        candidates = [record for record in records if record.body != query.body]
        ranked_ids = random_ranking(
            [record.image_id for record in candidates], seed=seed + query_index
        )
        relevant = {record.image_id for record in candidates if record.label == query.label}
        direction = f"{query.body}_to_{'mars' if query.body == 'earth' else 'earth'}"
        metrics[f"{direction}_p1"].append(precision_at_k(ranked_ids, relevant, 1))
        metrics[f"{direction}_p5"].append(precision_at_k(ranked_ids, relevant, 5))
        results[query.image_id] = [
            {"image_id": image_id, "score": None} for image_id in ranked_ids[:5]
        ]
    means = {key: float(np.mean(values)) for key, values in metrics.items()}
    means["macro_p1"] = float(np.mean([means["earth_to_mars_p1"], means["mars_to_earth_p1"]]))
    means["macro_p5"] = float(np.mean([means["earth_to_mars_p5"], means["mars_to_earth_p5"]]))
    return {
        "method": "random (seeded)",
        "evaluation_basis": basis,
        "metrics": means,
        "rankings": results,
    }


def _measure_patch_processing_sample(records: list[PatchRecord]) -> dict[str, Any]:
    """Time one representative extraction per body/category, cached by exact inputs."""
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    by_id = {row["image_id"]: row for row in plan["rows"]}
    selected: list[dict[str, Any]] = []
    for body in ("earth", "mars"):
        for label in LABELS:
            record = next(item for item in records if item.body == body and item.label == label)
            selected.append(by_id[record.image_id])
    records_by_id = {record.image_id: record for record in records}
    input_signature = [
        {
            "image_id": row["image_id"],
            "source_id": row["source_id"],
            "center_x": row["center_x"],
            "center_y": row["center_y"],
            "extent_m": row["extent_m"],
            "patch_checksum": records_by_id[row["image_id"]].checksum_sha256,
        }
        for row in selected
    ]
    cache_key = hashlib.sha256(
        json.dumps(input_signature, sort_keys=True).encode("utf-8")
    ).hexdigest()
    if PATCH_TIMING_CACHE.is_file():
        cached = json.loads(PATCH_TIMING_CACHE.read_text(encoding="utf-8"))
        if cached.get("input_sha256") == cache_key:
            return cached

    earth_catalog = pilot.Client.open(pilot.PC_STAC)
    mars_catalog = pilot.Client.open(pilot.MARS_STAC)
    samples: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="twinworld-pilot-timing-") as temp_dir:
        for row in selected:
            destination = Path(temp_dir) / f"{row['image_id']}.tif"
            try:
                href = pilot._source_href(row, earth_catalog, mars_catalog)
                bands = (1, 2, 3) if row["body"] == "earth" else (1,)
                started = time.perf_counter()
                geometry = extract_metric_patch(
                    href,
                    destination,
                    center_x=float(row["center_x"]),
                    center_y=float(row["center_y"]),
                    extent_m=float(row["extent_m"]),
                    native_gsd_m=float(row["native_gsd_m"]),
                    bands=bands,
                    min_valid_fraction=0.95,
                )
                elapsed = time.perf_counter() - started
                samples.append(
                    {
                        "image_id": row["image_id"],
                        "body": row["body"],
                        "category": row["proposed_label"],
                        "source_id": row["source_id"],
                        "seconds": elapsed,
                        "valid_pixel_fraction": geometry.valid_pixel_fraction,
                        "pixel_dimensions": [geometry.width_pixels, geometry.height_pixels],
                    }
                )
            except Exception as exc:
                samples.append(
                    {
                        "image_id": row["image_id"],
                        "body": row["body"],
                        "category": row["proposed_label"],
                        "source_id": row["source_id"],
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
    measured = [float(sample["seconds"]) for sample in samples if "seconds" in sample]
    result: dict[str, Any] = {
        "input_sha256": cache_key,
        "method": "one representative source-backed patch per planet/category",
        "network_read_and_warp_included": True,
        "samples": samples,
        "measured_count": len(measured),
        "requested_count": len(selected),
        "total_seconds": sum(measured),
        "mean_seconds": float(np.mean(measured)) if measured else None,
        "median_seconds": float(np.median(measured)) if measured else None,
    }
    if result["measured_count"] == result["requested_count"]:
        PATCH_TIMING_CACHE.parent.mkdir(parents=True, exist_ok=True)
        PATCH_TIMING_CACHE.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result



def run(device: str, model_profile: str = "dinov2_small") -> Path:
    """Run the configured retrieval benchmark and write its local HTML report."""
    model_profiles = MODEL_CONFIG["models"]
    if model_profile not in model_profiles:
        raise ValueError(f"Unknown model profile: {model_profile}")
    model = model_profiles[model_profile]
    model_id = str(model["model_id"])
    revision = str(model["revision"])
    expected_dimension = int(model["embedding_dimension"])
    records = read_jsonl(MANIFEST)
    if len(records) != 100:
        raise ValueError(f"expected exactly 100 manifest records, found {len(records)}")
    if len({record.image_id for record in records}) != 100:
        raise ValueError("pilot manifest contains duplicate image IDs")
    if Counter(record.body for record in records) != Counter({"earth": 50, "mars": 50}):
        raise ValueError("pilot must contain exactly 50 Earth and 50 Mars patches")
    manifest_errors = validate_records(records, ROOT)
    if manifest_errors:
        raise ValueError("invalid patch manifest: " + "; ".join(manifest_errors[:8]))
    for record in records:
        if file_sha256(ROOT / record.path) != record.checksum_sha256:
            raise ValueError(f"patch checksum mismatch for {record.image_id}")
    plan_path = ROOT / "data/manifests/pilot-plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_ids = {row["image_id"] for row in plan["rows"]}
    if plan_ids != {record.image_id for record in records}:
        raise ValueError("pilot plan and patch manifest image IDs differ")
    ensure_no_overlaps(plan["rows"])
    annotations = _annotations(ANNOTATIONS)
    labeled, basis = _evaluation_labels(records, annotations)
    category_counts = Counter((record.body, record.label) for record in labeled)
    if any(
        category_counts[(cast(Body, body), label)] != 10
        for body in ("earth", "mars")
        for label in LABELS
    ):
        raise ValueError("pilot requires exactly 10 samples per category and planet")
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    dino, dino_meta = embed_dinov2(
        records,
        ROOT,
        ARTIFACT_DIR,
        model_id=model_id,
        revision=revision,
        device_preference=device,  # type: ignore[arg-type]
    )
    expected_ids = [record.image_id for record in records]
    if dino.shape != (100, expected_dimension):
        raise ValueError(f"expected 100x{expected_dimension} DINOv2 embeddings, found {dino.shape}")
    if not np.isfinite(dino).all() or dino_meta.get("image_ids") != expected_ids:
        raise ValueError("DINOv2 embeddings are nonfinite or misaligned with manifest image IDs")
    if dino_meta.get("revision") != revision or dino_meta.get("model_id") != model_id:
        raise ValueError("DINOv2 artifact identity does not match the selected pinned profile")
    if device == "cuda" and dino_meta.get("device") != "cuda":
        raise ValueError(
            "requested CUDA inference but the embedding artifact reports another device"
        )
    patch_sample = _measure_patch_processing_sample(labeled)
    classical_started = time.perf_counter()
    classical, classical_cache_hit = _classical_features(records)
    classical_seconds = time.perf_counter() - classical_started
    retrieval_started = time.perf_counter()
    results = [
        _method_results("DINOv2", dino, labeled, basis),
        _method_results("HOG + LBP", classical, labeled, basis),
        _random_results(labeled, basis, seed=20261104),
    ]
    timings = {
        "classical_seconds": classical_seconds,
        "classical_cache_hit": classical_cache_hit,
        "retrieval_seconds": time.perf_counter() - retrieval_started,
    }
    result_payload = {
        "benchmark_id": "pilot-100-v1",
        "evaluation_basis": basis,
        "dino_metadata": dino_meta,
        "timings": timings,
        "patch_processing_sample": patch_sample,
        "image_ids": [record.image_id for record in records],
        "results": results,
    }
    (ARTIFACT_DIR / "pilot-benchmark.json").write_text(
        json.dumps(result_payload, indent=2) + "\n", encoding="utf-8"
    )
    labels: dict[str, Landform] = {record.image_id: record.label for record in labeled}
    previews = {record.image_id: _preview_data_uri(ROOT / record.path) for record in records}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        render_report(
            records,
            labels,
            results,
            basis,
            dino_meta,
            timings,
            patch_sample,
            previews,
        ),
        encoding="utf-8",
    )
    return REPORT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=("auto", "cuda", "cpu", "mps"), default="auto")
    parser.add_argument(
        "--model-profile",
        choices=tuple(MODEL_CONFIG["models"]),
        default="dinov2_small",
        help="Pinned model profile from configs/models.yaml",
    )
    args = parser.parse_args()
    print(f"wrote {run(args.device, args.model_profile)}")


if __name__ == "__main__":
    main()

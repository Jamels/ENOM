#!/usr/bin/env python3
"""Run cross-planet retrieval on the 100-patch pilot with a pinned DINOv2 profile."""

# Long lines are intentional in the embedded HTML report template.
# ruff: noqa: E501, I001

from __future__ import annotations

import argparse
import csv
import hashlib
import html
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


def _html_report(
    records: list[PatchRecord],
    labels: dict[str, Landform],
    results: list[dict[str, Any]],
    basis: str,
    inference_metadata: dict[str, Any],
    timings: dict[str, Any],
    patch_sample: dict[str, Any],
) -> str:
    counts = Counter((record.body, labels[record.image_id]) for record in records)
    summaries = []
    for result in results:
        m = result["metrics"]
        summaries.append(
            "<tr><td>"
            + html.escape(result["method"])
            + "</td>"
            + "".join(
                f"<td>{m[k]:.3f}</td>"
                for k in (
                    "earth_to_mars_p1",
                    "earth_to_mars_p5",
                    "mars_to_earth_p1",
                    "mars_to_earth_p5",
                    "macro_p1",
                    "macro_p5",
                )
            )
            + "</tr>"
        )
    dino = next(result for result in results if result["method"] == "DINOv2")
    metadata = {
        record.image_id: {
            "body": record.body,
            "label": labels[record.image_id],
            "latitude": record.latitude,
            "longitude": record.longitude,
            "native_gsd_m": record.native_gsd_m,
            "provider": record.provider,
            "source_id": record.source_id,
            "source_url": record.source_url,
        }
        for record in records
    }
    previews = {record.image_id: _preview_data_uri(ROOT / record.path) for record in records}
    candidate_pairs: list[tuple[float, str, str]] = []
    for query in records:
        for item in dino["rankings"][query.image_id]:
            candidate_pairs.append((float(item["score"]), query.image_id, str(item["image_id"])))

    def top_pairs(agree: bool) -> list[dict[str, Any]]:
        chosen: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for score, query_id, match_id in sorted(
            candidate_pairs, key=lambda item: item[0], reverse=True
        ):
            if (labels[query_id] == labels[match_id]) != agree:
                continue
            key = (min(query_id, match_id), max(query_id, match_id))
            if key in seen:
                continue
            seen.add(key)
            chosen.append({"score": score, "query_id": query_id, "match_id": match_id})
            if len(chosen) == 5:
                break
        return chosen

    rankings_json = json.dumps(dino["rankings"], ensure_ascii=False).replace("</", "<\\/")
    metadata_json = json.dumps(metadata, ensure_ascii=False).replace("</", "<\\/")
    previews_json = json.dumps(previews).replace("</", "<\\/")
    promising_json = json.dumps(top_pairs(True)).replace("</", "<\\/")
    misleading_json = json.dumps(top_pairs(False)).replace("</", "<\\/")
    options = "".join(
        f'<option value="{html.escape(record.image_id)}">'
        f"{html.escape(record.body)} · {html.escape(labels[record.image_id])} · "
        f"{html.escape(record.image_id)}</option>"
        for record in records
    )
    distribution = " · ".join(
        f"{body}: {label}={count}" for (body, label), count in sorted(counts.items())
    )
    providers = ", ".join(sorted({record.provider for record in records}))
    source_groups: dict[tuple[str, str], list[PatchRecord]] = {}
    for record in records:
        source_groups.setdefault((record.body, record.provider), []).append(record)
    source_rows = "".join(
        "<tr>"
        f"<td>{html.escape(body)}</td><td>{html.escape(provider)}</td>"
        f"<td>{len(group)}</td><td>{len({record.source_id for record in group})}</td>"
        f"<td>{min(record.native_gsd_m for record in group):g}–"
        f"{max(record.native_gsd_m for record in group):g} m/px</td></tr>"
        for (body, provider), group in sorted(source_groups.items())
    )
    geographic_groups = Counter((record.body, record.geographic_group) for record in records)
    geography_rows = "".join(
        f"<tr><td>{html.escape(body)}</td><td>{html.escape(group)}</td><td>{count}</td></tr>"
        for (body, group), count in sorted(geographic_groups.items())
    )
    patch_times = [
        float(record.processing["patch_processing_seconds"])
        for record in records
        if "patch_processing_seconds" in record.processing
    ]
    dino_time = inference_metadata.get("elapsed_seconds")
    dino_gpu = inference_metadata.get("gpu_name", "not reported")
    patch_timing_text = (
        f"{len(patch_times)} of {len(records)} patches have measured extraction durations; "
        f"their summed duration is {sum(patch_times):.2f} seconds."
        if patch_times
        else (
            f"Representative patch processing sample: {patch_sample['measured_count']} of "
            f"{patch_sample['requested_count']} crops measured; mean "
            f"{patch_sample['mean_seconds'] if patch_sample['mean_seconds'] is not None else 'unavailable'} "
            f"seconds, median {patch_sample['median_seconds'] if patch_sample['median_seconds'] is not None else 'unavailable'} "
            f"seconds, total {patch_sample['total_seconds']:.3f} seconds. Network COG reads and metric warps are included; this is a 10-crop sample, not full-dataset wall time."
        )
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>TwinWorld pilot evaluation</title><style>body{{font:15px/1.5 system-ui;margin:24px;color:#18232d}}.note{{padding:12px;background:#fff1cc}}table{{border-collapse:collapse}}td,th{{border:1px solid #ccd4dc;padding:7px}}.strip{{display:flex;gap:5px;overflow:auto}}.strip img{{width:150px;height:150px;object-fit:contain;background:#17212b}}section,article{{margin:16px 0;padding:14px;background:#f3f5f7}}a{{overflow-wrap:anywhere}}select{{max-width:100%;padding:8px}}</style>
<h1>TwinWorld · 100 image retrieval pilot</h1><p class="note">Evaluation basis: {html.escape(basis)}. Category agreement is not a scientific relevance judgement. No cross-planet analogue claim is established by image similarity.</p>
<h2>Dataset</h2><p>{len(records)} images · {sum(r.body == "earth" for r in records)} Earth · {sum(r.body == "mars" for r in records)} Mars</p><p>{html.escape(distribution)}</p>
<p>All crops are 2 km square; native GSD range {min(r.native_gsd_m for r in records):g}–{max(r.native_gsd_m for r in records):g} m/px. Providers: {html.escape(providers)}. DINOv2 uses grayscale percentile stretch replicated to RGB 224x224. Classical descriptor: HOG plus uniform LBP. Similarity: cosine.</p>
<h3>Sensor and native resolution</h3><table><thead><tr><th>Planet</th><th>Provider / sensor source</th><th>Images</th><th>Distinct source products</th><th>Native GSD</th></tr></thead><tbody>{source_rows}</tbody></table>
<h3>Geographic coverage</h3><table><thead><tr><th>Planet</th><th>Region group</th><th>Patches</th></tr></thead><tbody>{geography_rows}</tbody></table>
<h2>Retrieval comparison</h2><table><thead><tr><th>Method</th><th>E→M P@1</th><th>E→M P@5</th><th>M→E P@1</th><th>M→E P@5</th><th>Macro P@1</th><th>Macro P@5</th></tr></thead><tbody>{"".join(summaries)}</tbody></table>
<p>P@k means fraction of the top k results whose proposed category matches the query category. With 10 of each category per planet, random expected P@k is 0.20. These scores remain provisional until labels are independently reviewed.</p>
<h2>Processing and inference timings</h2><p>DINOv2 inference: {f"{dino_time:.3f} seconds" if isinstance(dino_time, (int, float)) else "not reported"}; throughput {inference_metadata.get("images_per_second", "not reported")} images/s; device {html.escape(str(inference_metadata.get("device", "unknown")))}; GPU {html.escape(str(dino_gpu))}; model {html.escape(str(inference_metadata.get("model_id", "unknown")))} revision {html.escape(str(inference_metadata.get("revision", "unknown")))}.</p><p>HOG/LBP feature pass: {timings["classical_seconds"]:.3f} seconds (cache hit: {timings["classical_cache_hit"]}); retrieval scoring/evaluation: {timings["retrieval_seconds"]:.3f} seconds. {patch_timing_text}</p>
<h2>DINOv2 top-five for every query</h2><label for="query">Choose a query (all 100 are available):</label> <select id="query">{options}</select><div id="query-results"></div>
<h2>Potential analogue candidates for independent review</h2><p>Pairs agree with provisional categories. This is a review queue, not evidence of geological equivalence.</p><div id="promising"></div>
<h2>Potentially misleading candidates for independent review</h2><p>Pairs disagree with provisional categories despite high image similarity. These are not human-confirmed failures.</p><div id="misleading"></div>
<h2>Provenance and full rankings</h2><p>Inspect <code>pilot-benchmark.json</code> and <code>pilot-100.jsonl</code> for complete rankings, source IDs, coordinates, resolution, and source links.</p>
<script>
const rankings={rankings_json}; const metadata={metadata_json}; const previews={previews_json};
const promising={promising_json}; const misleading={misleading_json};
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
function img(id){{return `<img src="${{previews[id]}}" alt="${{esc(id)}}">`;}}
function details(id){{const r=metadata[id];return `${{esc(r.body)}} · ${{esc(r.label)}} · ${{Number(r.latitude).toFixed(5)}}, ${{Number(r.longitude).toFixed(5)}} · ${{r.native_gsd_m}} m/px · ${{esc(r.provider)}} · <a href="${{esc(r.source_url)}}">${{esc(r.source_id)}}</a>`;}}
function renderQuery(){{const id=document.querySelector('#query').value;const items=rankings[id];document.querySelector('#query-results').innerHTML=`<article><h3>Query: ${{esc(id)}}</h3><p>${{details(id)}}</p><div class="strip">${{img(id)}}${{items.map(x=>img(x.image_id)).join('')}}</div><ol>${{items.map(x=>`<li>${{details(x.image_id)}} · cosine ${{Number(x.score).toFixed(4)}}</li>`).join('')}}</ol></article>`;}}
function renderPairs(target,items,heading){{document.querySelector(target).innerHTML=items.length?items.map(x=>`<article><b>${{heading}} · cosine ${{x.score.toFixed(4)}}</b><div class="strip">${{img(x.query_id)}}${{img(x.match_id)}}</div><p>${{details(x.query_id)}} ↔ ${{details(x.match_id)}}</p></article>`).join(''):'<p>Fewer than five candidates were returned.</p>';}}
document.querySelector('#query').addEventListener('change',renderQuery);renderQuery();
renderPairs('#promising',promising,'Category agreement');renderPairs('#misleading',misleading,'Category disagreement');
</script>
</html>"""


def run(device: str, model_profile: str = "dinov2_small") -> Path:
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
        raise ValueError(
            f"expected 100x{expected_dimension} DINOv2 embeddings, found {dino.shape}"
        )
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
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        _html_report(records, labels, results, basis, dino_meta, timings, patch_sample),
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

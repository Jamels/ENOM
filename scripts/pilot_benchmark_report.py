"""Render the standalone HTML report for a pilot retrieval benchmark."""

# ruff: noqa: E501

from __future__ import annotations

import html
import json
from collections import Counter
from typing import Any

from twinworld.records import Landform, PatchRecord


def render_report(
    records: list[PatchRecord],
    labels: dict[str, Landform],
    results: list[dict[str, Any]],
    basis: str,
    inference_metadata: dict[str, Any],
    timings: dict[str, Any],
    patch_sample: dict[str, Any],
    preview_data_uris: dict[str, str],
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
    previews = preview_data_uris
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



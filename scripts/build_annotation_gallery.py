#!/usr/bin/env python3
"""Build a standalone, offline review gallery for the pilot image manifest."""

# Long lines are intentional in the embedded HTML, CSS, and JavaScript template.
# ruff: noqa: E501

from __future__ import annotations

import argparse
import base64
import csv
import html
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/manifests/pilot-100.jsonl"
ANNOTATIONS = ROOT / "data/annotations/pilot-100.csv"
OUTPUT = ROOT / "reports/pilot-annotation-gallery.html"
LABELS = (
    "barchan_crescent_dune",
    "linear_dune",
    "other_dune",
    "rocky_ridge_layered",
    "other_non_dune",
    "unknown",
)
FIELDS = (
    "image_id",
    "proposed_label",
    "reviewed_label",
    "review_status",
    "ambiguity_notes",
    "source_reference",
    "annotator_id",
    "reviewed_at",
    "review_rationale",
)


def _preview_data_uri(path: Path) -> str:
    with rasterio.open(path) as dataset:
        values = dataset.read().astype(np.float32)
    valid = np.isfinite(values).all(axis=0)
    if not valid.any():
        raise ValueError(f"patch contains no valid pixels: {path}")
    channels: list[np.ndarray] = []
    for band in values[:3]:
        sample = band[np.isfinite(band)]
        low, high = np.percentile(sample, (2, 98))
        if high <= low:
            high = low + 1
        channels.append(np.clip((np.nan_to_num(band, nan=low) - low) / (high - low), 0, 1))
    if len(channels) == 1:
        channels *= 3
    rgb = np.stack(channels, axis=-1)
    rgb[~valid] = 0
    image = Image.fromarray(np.round(rgb * 255).astype(np.uint8), mode="RGB")
    image.thumbnail((320, 320), Image.Resampling.LANCZOS)
    import io

    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _load_rows(manifest_path: Path, annotations_path: Path) -> list[dict[str, Any]]:
    records = [
        json.loads(line)
        for line in manifest_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    with annotations_path.open(encoding="utf-8", newline="") as source:
        annotations = {row["image_id"]: row for row in csv.DictReader(source)}
    rows = []
    for record in records:
        annotation = annotations.get(record["image_id"], {})
        rows.append(
            {
                **{field: annotation.get(field, "") for field in FIELDS},
                "image_id": record["image_id"],
                "proposed_label": annotation.get("proposed_label") or record["label"],
                "body": record["body"],
                "longitude": record["longitude"],
                "latitude": record["latitude"],
                "native_gsd_m": record["native_gsd_m"],
                "width_m": record["width_m"],
                "provider": record["provider"],
                "source_id": record["source_id"],
                "source_reference": annotation.get("source_reference") or record["source_url"],
                "preview": _preview_data_uri(ROOT / record["path"]),
            }
        )
    return sorted(rows, key=lambda row: row["image_id"])


def build_gallery(
    manifest_path: Path = MANIFEST,
    annotations_path: Path = ANNOTATIONS,
    output_path: Path = OUTPUT,
) -> Path:
    rows = _load_rows(manifest_path, annotations_path)
    distributions = Counter((row["body"], row["proposed_label"]) for row in rows)
    payload = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>TwinWorld pilot annotation review</title>
<style>
body{{font:15px/1.45 system-ui,sans-serif;margin:0;background:#f4f6f8;color:#17212b}}
header{{position:sticky;top:0;background:#fff;padding:16px 4vw;box-shadow:0 2px 12px #0002;z-index:2}}
h1{{font-size:1.25rem;margin:0 0 6px}}.summary{{color:#536272}}button{{padding:9px 14px;margin:8px 8px 0 0}}
main{{padding:20px 4vw;display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}}
article{{background:white;border:1px solid #dce2e8;border-radius:10px;overflow:hidden}}
article img{{width:100%;height:260px;object-fit:contain;background:#101820}}
.body{{padding:12px}}.meta{{font-size:.88rem;color:#44515e;margin:5px 0}}label{{display:block;margin-top:9px}}
select,input,textarea{{width:100%;box-sizing:border-box;padding:7px;margin-top:3px}}textarea{{min-height:55px}}
a{{color:#155f92}}.badge{{font-weight:650}}
</style></head><body>
<header><h1>TwinWorld · pilot image review</h1>
<div class="summary">{len(rows)} source-backed patches · labels are proposals until independently reviewed. Review before viewing retrieval results.</div>
<div class="summary">{html.escape(" · ".join(f"{body}: {label}={count}" for (body, label), count in sorted(distributions.items())))}</div>
<button id="download">Download reviewed CSV</button><button id="save">Save progress in this browser</button>
<span id="status" role="status"></span></header><main id="cards"></main>
<script>
const rows={payload};
const fields={json.dumps(FIELDS)};
const labels={json.dumps(LABELS)};
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
function render(){{const root=document.querySelector('#cards');root.innerHTML=rows.map((r,i)=>`<article data-index="${{i}}">
<img loading="lazy" src="${{r.preview}}" alt="${{esc(r.body)}} image patch ${{esc(r.image_id)}}"><div class="body">
<div class="badge">${{esc(r.image_id)}} · ${{esc(r.body)}} · proposal: ${{esc(r.proposed_label)}}</div>
<div class="meta">${{Number(r.latitude).toFixed(5)}}, ${{Number(r.longitude).toFixed(5)}} · ${{r.width_m}} m · native ${{r.native_gsd_m}} m/px</div>
<div class="meta">${{esc(r.provider)}} · <a href="${{esc(r.source_reference)}}" target="_blank" rel="noreferrer">${{esc(r.source_id)}}</a></div>
<label>Reviewed label<select data-field="reviewed_label"><option value="">Select after inspection</option>${{labels.map(x=>`<option value="${{esc(x)}}">${{esc(x.replaceAll('_',' '))}}</option>`).join('')}}</select></label>
<label>Review status<select data-field="review_status"><option>unreviewed</option><option>reviewed</option><option>uncertain</option></select></label>
<label>Annotator<input data-field="annotator_id" autocomplete="off"></label>
<label>Rationale<textarea data-field="review_rationale"></textarea></label></div></article>`).join('');
for(const card of root.children){{const r=rows[Number(card.dataset.index)];for(const el of card.querySelectorAll('[data-field]'))el.value=r[el.dataset.field]||'';}}
}}
function collect(){{for(const card of document.querySelectorAll('article')){{const r=rows[Number(card.dataset.index)];for(const el of card.querySelectorAll('[data-field]'))r[el.dataset.field]=el.value;}}}}
document.querySelector('#download').onclick=()=>{{collect();const now=new Date().toISOString();const csv=[fields.join(','),...rows.map(r=>fields.map(f=>{{let v=r[f]||'';if(f==='reviewed_at'&&r.review_status==='reviewed'&&!v)v=now;return '"'+String(v).replaceAll('"','""')+'"';}}).join(','))].join('\r\n');const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{{type:'text/csv'}}));a.download='pilot-100-reviewed.csv';a.click();URL.revokeObjectURL(a.href);}};
document.querySelector('#save').onclick=()=>{{collect();const annotations=rows.map(r=>Object.fromEntries(['image_id',...fields.slice(1)].map(k=>[k,r[k]||''])));localStorage.setItem('twinworld-pilot-review',JSON.stringify(annotations));document.querySelector('#status').textContent='Progress saved in this browser.';}};
const saved=localStorage.getItem('twinworld-pilot-review');if(saved){{try{{const old=JSON.parse(saved);const byId=new Map(old.map(x=>[x.image_id,x]));for(const r of rows)Object.assign(r,byId.get(r.image_id)||{{}});}}catch{{}}}}
render();
</script></body></html>"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(page, encoding="utf-8")
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--annotations", type=Path, default=ANNOTATIONS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build_gallery(args.manifest, args.annotations, args.output)
    print(f"wrote {result}")


if __name__ == "__main__":
    main()

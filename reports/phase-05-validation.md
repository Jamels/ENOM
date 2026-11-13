# Phase 0.5 validation

## Repository data and provenance

- Pilot manifest: 100 records (50 Earth, 50 Mars); schema/provenance validation reports zero errors.
- All 100 local patch files match the SHA-256 values in `pilot-100.jsonl`.
- 21 terrain JSON sidecars cover 10 Copernicus contexts, 10 MOLA contexts, and one bounded LOLA scorecard crop. Each contains source identity or catalog reference, processing, and measurement provenance. The Copernicus source URL is carried in measurement provenance and `source_catalog_url` at sidecar level.
- The 100-image visual matrix order and dimension are checked against metadata by the API. Large rasters, local embeddings, and model weights remain ignored.
- Candidate-location catalogue coordinates are bounded and source-linked. Proposed positive/negative review pairs reference real pilot IDs and remain pending; no retrieval metrics are computed from them.

## Automated checks

- `pytest -q`: **43 passed**.
- Ruff: **passed**.
- mypy: **passed** for 17 source modules.
- Frontend production build: **passed** (`tsc -b`, Vite).
- Pilot manifest CLI validation: **100 records valid**.
- Local Uvicorn HTTP demonstration: `/api/health` returned 100 records and a populated visual index; combined retrieval returned 3 requested results; scorecard sites returned one lunar site; scorecard ranking returned 10 ingested Earth DEM contexts with provenance.
- `scripts/run_phase05_evaluation.py`: **8 queries**, 18 terrain-eligible observations, 62 combined-result rank changes recorded. This is a behavior/latency demonstration, not accuracy evaluation.
- DINOv2 benchmark CLI help: passed; it exposes pinned `dinov2_small` and `dinov2_base` profiles and `auto`/CUDA/MPS/CPU device selection without starting inference.
- `uv sync --locked --extra dev --extra earthdata`: passed. No dependency lockfile changes were needed.

## Not performed / limitations

- No CUDA, MPS, or CPU embedding regeneration was performed; the existing 384-D DINOv2-small matrix was reused. DINOv2-base configuration is present but no base model was downloaded or run.
- No browser click-through or visual basemap comparison was performed. Earth/Mars use the existing equirectangular locator; there is no Moon polar map or tiled basemap.
- The LOLA scorecard crop is near-equatorial `LDEM_64`, not a south-polar product. The gridded product does not quantify direct-shot support for this crop, and derived terrain uncertainties are not quantified.
- No independently reviewed relevance judgments exist. The proposed review set must be blinded and adjudicated before reporting precision/recall or accuracy.
- Source-image acquisition/illumination and preprocessing sensitivity have not been quantified. Current image preprocessing is fixed in the artifact identity; benchmark variants are configured but no robustness result is claimed.
- MOLA observed-cell support is 19.8%–50.0%; the default 25% engineering quality threshold excludes two of ten contexts. This is not a validated scientific threshold.
- No retrieval or scorecard result establishes geological equivalence, mission suitability, cave geometry, or field-site utility.

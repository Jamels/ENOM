# ENOM / TwinWorld Phase 0.5

ENOM is an evidence-first planetary surface discovery prototype. TwinWorld combines a FastAPI service, a React/TypeScript explorer, source-backed image manifests, visual embeddings, optional terrain observations, and explicit comparison provenance. A retrieved pair is a research lead, not proof that two locations share geology or are mission-suitable.

## Implemented now

- A source-backed 100-image pilot: 50 Earth and 50 Mars observations in `data/manifests/pilot-100.jsonl`. Raster image assets and the precomputed DINOv2-small matrix are local generated/downloaded artifacts excluded from Git; manifests, checksums, scripts, and metadata remain in the repository.
- A pinned DINOv2 ViT-S/14 (`facebook/dinov2-small`) visual index with 384-dimensional embeddings. Inference supports CUDA, Apple Silicon MPS, and CPU selection. DINOv2 ViT-B/14 (768 dimensions) has a separate cache namespace and configuration; no model download or re-embedding is needed for the existing pilot.
- FastAPI endpoints for health, indexed observations, datasets/coverage, search, and pair comparisons. The API reads one identity-checked embedding matrix and returns provenance, measurement availability, evidence quality, and known data gaps.
- A React/TypeScript/Vite explorer for Earth and Mars indexed records with visual, terrain-only, and combined retrieval. Terrain scoring excludes candidates without adequate coverage and comparable units/scales. Unimplemented scientific objectives are marked unavailable.
- Scale-explicit terrain extraction and available Copernicus GLO-30 Earth and MOLA MEG128 Mars contexts. MOLA count rasters separate measured bins from interpolated topography. Sparse coverage is not treated as complete terrain truth.
- An interactive NASA-first Moon–Earth terrain scorecard. A bounded NASA LRO LOLA GDR `LDEM_64` crop for Mare Tranquillitatis is compared with existing Copernicus GLO-30 Earth contexts using same-unit, scale-matched local terrain features, adjustable validated weights, explicit provenance, and separate provisional mission screening.
- Typed scientific comparison records and a candidate-location catalogue covering lunar south-polar targets, lunar volcanic/pit settings, Mars exploration sites, hyper-arid deserts, polar deserts, volcanic terrain, and caves. Catalogue membership is not an analogue validation label and is independent of imagery/raster availability.
- Lunar coordinate/LOLA product foundations and spherical north/south polar stereographic helpers. Moon remains outside the image-search index; the scorecard is a separate terrain-based Moon–Earth flow, not a lunar image-search integration.

## Scientific limits

- Pilot patch labels are unreviewed, and there are no independent analogue relevance judgments. Do not report retrieval accuracy or validated analogue performance.
- Visual similarity, terrain similarity, evidence quality, and mission suitability are distinct claims. Visual cosine is a retrieval value, not a physical-similarity percentage. Terrain ranks are descriptive and do not validate geological equivalence.
- MOLA MEG128 has sparse shot support at the indexed context scale. Count-grid coverage is surfaced; missing/interpolated cells are excluded. Sampled elevation range may miss unsampled extrema.
- Sources differ in sensor, spectrum, ground sampling distance, illumination, season, and processing. Preprocessing variants are evaluation treatments, not proof of invariance.
- Earth and Mars use different reference surfaces and radii. Absolute elevations across bodies are not compared. The current equirectangular map is a locator without tiled basemaps.
- LOLA `LDEM_64` is an interpolated shape/radius grid without per-pixel observation confidence in the ingested product; direct-shot coverage and terrain-feature uncertainty are unquantified. The scorecard reports these gaps.
- Mission screening limits are provisional research assumptions, not validated vehicle requirements. Earth analogue-site suitability, cave geometry, traversability, mineralogy, and thermal environment are not inferred from image or terrain similarity.

## macOS setup

Python 3.12 and Node.js are required. PyTorch can select MPS on Apple Silicon, CUDA on supported NVIDIA systems, or CPU fallback.

```sh
uv sync --extra dev --extra vision --extra earthdata
uv run uvicorn twinworld.api:app --reload
```

In another terminal:

```sh
cd apps/twinworld
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`; API docs are at `http://127.0.0.1:8000/api/docs`. A fresh clone must obtain pilot imagery and the corresponding embedding artifact before indexed search works: large local assets are intentionally excluded from Git. Follow manifest source URLs, checksums, and preparation scripts.

`configs/models.yaml` records model IDs, immutable revisions, dimensions, and cache names. `TWINWORLD_EMBEDDINGS` selects the API index. Embedding caches are separated by model ID; each artifact records model revision and preprocessing identity. Model weights are not downloaded during setup, only when inference is explicitly run.

## Reproducible checks and demo

```sh
uv run --extra dev pytest -q
uv run --extra dev ruff check .
uv run --extra dev mypy src/twinworld
cd apps/twinworld && npm ci && npm run build
```

The suite includes API, retrieval, terrain, MOLA, provenance, lunar-coordinate, and catalogue checks. `uv run python scripts/run_phase05_evaluation.py` runs the local in-process retrieval demonstration and refreshes `reports/phase-05-evaluation.md`; it requires the local pilot manifest, embedding matrix/metadata, and terrain sidecars. It reports ranking behavior and latency, not accuracy. See `docs/DATA_SOURCES.md`, `docs/DATA_SOURCE_REGISTRY.md`, `docs/METHODOLOGY.md`, and `docs/MULTIMODAL_METHODOLOGY.md` for preparation and provenance.

## Candidate catalogue and lunar data

`data/manifests/candidate-locations.json` contains sourced coordinates, candidate types/statuses, and dataset references. It does not assert raster coverage. Coordinates use east-positive `[0, 360)`; lunar polar products must retain their source-defined reference frame and projection. The catalogue endpoint is `/api/catalogue`.

LOLA references: [PDS GDR overview](https://ode.rsl.wustl.edu/moon/pagehelp/Content/Missions_Instruments/Lunar%20Reconnaissance%20Orbiter%20%28LRO%29/LOLA/GDR/Intro.htm), [GDR counts semantics](https://ode.rsl.wustl.edu/moon/pagehelp/Content/Missions_Instruments/Lunar%20Reconnaissance%20Orbiter%20%28LRO%29/LOLA/GDR/GDRDEC.htm), [NASA GSFC south-pole products](https://pgda.gsfc.nasa.gov/products/90).

For the operational LOLA crop, exact product, access, measurement definitions and limitations, run instructions, and scorecard methodology, see `docs/NASA_SCORECARD_METHODOLOGY.md` and `docs/DATA_SOURCE_REGISTRY.md`. The scorecard is available from **NASA scorecards** in the web UI; its API is documented in `/api/docs` when running locally.

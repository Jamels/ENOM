# TwinWorld explorer UI and API

For the full system diagram and module responsibilities, see
[ARCHITECTURE.md](ARCHITECTURE.md). This page focuses on the browser boundary,
user flow, and current interface limitations.

## Implemented architecture

- **FastAPI** in `src/twinworld/api.py` owns the pilot manifest, image/terrain evidence, dataset coverage, retrieval ordering, pair comparisons, and provenance payloads. The `/api/docs` schema is the API reference.
- **React + TypeScript + Vite** in `apps/twinworld` renders the indexed Earth/Mars explorer. It requests observations, profiles, search results, and comparisons from the API; the client does not calculate scientific ranks or invent measurements.
- **Pilot index** contains 100 imagery records (50 Earth and 50 Mars). The source assets and 384-D DINOv2-small matrix are local ignored artifacts; JSONL manifests and embedding metadata carry source identity, checksums, model revision, and processing context.

## Current user flow

1. Load indexed records and scientific objective availability from `/api/regions` and `/api/profiles`.
2. Choose Earth or Mars and select a source-backed pilot observation.
3. Inspect its location in an east-positive equirectangular locator. It has no basemap and does not preserve equal distance or area. Source links and native resolution are shown in details.
4. Submit `/api/search` in visual, terrain, or combined mode. Visual uses exact DINOv2 cosine ordering. Terrain requires adequate coverage and comparable units/scales. Combined keeps the visual and terrain evidence separately inspectable and reports ranking differences.
5. Select a result to inspect its image, source and terrain evidence, measurement differences, uncertainty, quality coverage, and unavailable data from `/api/comparisons/{query}/{candidate}`.

## Scientific representation

Search outputs separate visual scores, terrain scores, and evidence availability. These values do not represent mission suitability or validated geological similarity. Sparse MOLA support is described using shot-count coverage; unobserved/interpolated cells are not treated as measurements. Unsupported objectives remain marked unavailable.

`/api/catalogue` exposes sourced candidate locations separately from indexed observations. The separate scorecard view uses `/api/scorecards/sites`, `/api/scorecards/config`, and `/api/scorecards/rank` to compare available LOLA or MOLA reference terrain with Earth DEM contexts. It keeps terrain similarity and provisional mission screening separate and includes source links and data-quality caveats. `/api/planets` still reports Moon as unavailable for image retrieval because lunar imagery is not indexed. The current LOLA crop is near-equatorial; a south-polar map and native polar-product ingestion remain future work.

## Mapping and accessibility status

The current locator uses global equirectangular longitude/latitude placement for indexed Earth and Mars patches. It communicates longitude convention and source attribution, but provides no real basemap, lunar polar projection view, or planetary tiled imagery. Basemap integration must respect each body's native datum, projection, product frame, and provider attribution; lunar south-polar LOLA products are especially frame-sensitive. Keyboard operation, narrow viewport layouts, loading/error states, and visible unimplemented-profile status are implemented. Broader automated browser accessibility checks have not been added.

## Run locally

```sh
uv sync --extra dev
uv run uvicorn twinworld.api:app --reload
```

```sh
cd apps/twinworld
npm ci
npm run dev
```

Vite defaults to `http://127.0.0.1:5173`; FastAPI defaults to `http://127.0.0.1:8000`.

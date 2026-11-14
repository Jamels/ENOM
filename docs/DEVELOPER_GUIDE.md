# Developer guide

This guide maps common changes to the existing code. Start with the
architecture in [ARCHITECTURE.md](ARCHITECTURE.md), then use the focused source
module and tests named below. Keep generated rasters and model artifacts
reproducible from their manifests, configuration, and scripts.

## Repository map

- `src/twinworld/`: Python domain records, geospatial operations, features,
  retrieval, scorecards, and FastAPI service.
- `scripts/`: command-line data preparation, ingestion, and evaluation jobs.
- `configs/`: `models.yaml` and `pilot-sites.json` drive current workflows;
  the review set is checked into tests, while `benchmark-v1.yaml` is a planned
  specification not yet consumed by a command.
- `data/manifests/`: source-backed observations and candidate locations.
- `data/patches/`, `data/terrain/`: local raster assets and provenance sidecars.
- `data/geology/`: categorical regional Mars map-unit provenance records.
- `apps/twinworld/`: React + TypeScript + Vite client. `src/main.tsx` owns API loading and explorer state; `src/ScorecardView.tsx` renders the scorecard; `src/types.ts` defines API shapes.
- `tests/`: Python regression tests.
- `docs/`: scientific methodology, data provenance, reproducibility, and UI
  architecture notes.

## Common commands

From the repository root:

```sh
uv sync --extra dev
uv run uvicorn twinworld.api:app --reload
uv run pytest -q
uv run ruff check .
uv run mypy src/twinworld
```

Install `uv sync --extra dev --extra vision` for DINOv2 inference. Install
`uv sync --extra dev --extra earthdata` for the STAC-based pilot builder;
routine API and UI work does not need either extra.

In a second terminal:

```sh
cd apps/twinworld
npm ci
npm run dev
npm run build
```

The browser client uses `http://127.0.0.1:5173`; the API uses
`http://127.0.0.1:8000` and its OpenAPI page is at `/api/docs`. Visual search
needs local pilot rasters and a matching embedding matrix, which are not
included in a clean checkout. API startup and frontend builds do not create
those assets.

## Adding an Earth, Moon, or Mars location

First decide whether the location is an **indexed observation** (has image data
and belongs in image retrieval) or a **catalogue/scorecard location** (a sourced
place that may not have imagery or terrain coverage). Do not add a catalogue
entry to the image index just to make it appear in the interface.

For an indexed patch:

1. Add/select a source record in the relevant pilot configuration or discovery
   input. Retain source IDs, source URLs, acquisition time, sensor/product,
   coordinate reference, and native sampling.
2. Prepare a raster in a projected CRS and call
   `twinworld.patching.extract_metric_patch` with the intended ground extent
   and source sampling. It rejects geographic CRSs and insufficient valid
   source coverage.
3. Create a `PatchRecord` with body-appropriate longitude convention, label
   status, footprint dimensions, checksum, and processing details. Validate it
   with `twinworld.records.validate_records`.
4. Regenerate embeddings with the configured immutable model revision, retaining
   the metadata JSON beside the matrix. Do not reorder manifest rows without
   regenerating the matrix and metadata together.
5. Add or update tests for the coordinate convention, provenance, and resulting
   observation behavior.

The automatic Mars dune discovery in `scripts/build_pilot.py` starts with the
largest eligible MGD3 field in each class, then selects fields by farthest
great-circle distance on a Mars sphere. A refreshed plan may select a different
field because the distance calculation is part of the discovery algorithm.
`--plan-only` writes the plan without rebuilding patches or the manifest.
Linear-dune sampling uses four selected fields, allocating `3, 3, 2, 2` crops
per field. Each 2 km crop center must have at least five of nine nearby sample
points inside its MGD3 polygon, and selected crop centers must not overlap. A
field that cannot supply its allocation is omitted from the plan with a reason.

For a catalogue-only place, update `data/manifests/candidate-locations.json`
with sourced coordinates and label status. Catalogue membership does not imply
that the image index or a raster covers the location.

Coordinate conventions in the current records are not uniform at source
boundaries: Earth manifest longitudes are signed; Mars sources can be signed
and are normalized east-positive in API payloads; Moon catalogue/scorecard
longitudes are east-positive in `[0, 360)`. Use the relevant validator and
projection adapter instead of copying one body's conversion into another.

## Integrating a scientific dataset

1. Choose the product and bounded spatial/temporal window. Read its label and
   product documentation before interpreting pixel values.
2. Implement a focused adapter in `scripts/` for provider-specific discovery,
   download, byte-range access, decoding, scaling, and nodata handling.
3. Write an output raster in a CRS that preserves the source geometry needed by
   downstream calculations. Record source product ID/URL, retrieval date,
   dimensions, CRS, units, scale/offset, nodata semantics, support/coverage,
   and all resampling or masking steps in a JSON sidecar.
4. Keep observation values separate from support layers. For example, an
   interpolated elevation grid and an observation-count raster answer different
   questions; do not treat interpolation as a direct measurement.
5. Add a fixture-based test for decoding and a test for the derived measurement
   semantics. Prefer small local fixtures and mocked network responses over
   provider downloads in unit tests.
6. Link the product's methodology and known limitations from the relevant data
   documentation.

For categorical regional Mars geology, use
[`scripts/ingest_mars_geology.py`](../scripts/ingest_mars_geology.py):
`mapped_unit_at()` applies the source longitude convention and returns a unit
only when the coordinate falls uniquely inside a polygon. Unmapped and
boundary-ambiguous results remain explicit. The API attaches these records as
`geology_evidence`; do not turn map-unit codes into terrain measurements or
add them to `scorecards.VARIABLES`. `tests/test_scorecards.py` covers polygon
mapping states and verifies the evidence reaches the Mars scorecard without
loading the visual index.

## Adding a scorecard variable

1. Implement the measurement from its correctly projected input in
   `src/twinworld/terrain.py` or the product-specific adapter. Return a
   `PhysicalMeasurement` with explicit units, `spatial_scale_m`, availability,
   uncertainty note, and provenance.
2. Add its stable name, units, and ranking tolerance to `VARIABLES` in
   `src/twinworld/scorecards.py`. A tolerance is a ranking scale in the
   exponential transform, not a scientific error bar.
3. Add the variable and a justified weight to each applicable mission preset.
   Do not silently treat missing measurements as zero. Only finite,
   positive-scale measurements marked `available` can contribute; other
   availability states are excluded from ranking and mission screening. The
   comparison also excludes unit/scale-incompatible components, then reports
   completeness.
4. Add tests for an exact match, a known difference, a missing value, a unit
   mismatch, and a spatial-scale mismatch. For mission screening, cover missing
   values and inclusive cutoff boundaries separately from similarity.
5. Document the formula, input product, observation support, resolution, and
   assumptions near the implementation and in the scorecard methodology.

## Debugging failed processing

- **Manifest validation:** run `uv run twinworld
  data/manifests/pilot-100.jsonl`; inspect the reported record ID and field.
- **Absent imagery or embeddings:** check the manifest path, local ignored
  raster files, `TWINWORLD_EMBEDDINGS`, and adjacent embedding metadata. The
  matrix row order and `image_ids` must match the manifest exactly.
- **Raster processing errors:** inspect CRS, linear units, nodata, transform,
  pixel dimensions, and valid-cell fraction. Geographic degrees are not metres.
- **Unexpected terrain score:** inspect each component's availability, units,
  feature scale, tolerance, and weight in the API response. Only available,
  positive-weight components contribute to the score; completeness reports how
  many requested components were comparable.
- **Unexpected MOLA result:** inspect the paired count raster. Empty bins can
  contain interpolated elevations and must not be treated as observed samples.
- **HTTP failure:** open `/api/docs`, check the endpoint response and server
  log, then reproduce the request against the API before debugging the React
  rendering.
- **External data failure:** verify credentials, network access, provider
  availability, and product URLs. Do not record tokens in manifests, logs, or
  checked-in sidecars.

## Reproducing scientific results

Regenerate the checked-in Moon and Mars examples from the local NASA and Earth
terrain sidecars:

```sh
uv run python scripts/run_scorecard_demo.py
uv run python scripts/run_scorecard_demo.py --site mars_aeolis_nondune-01
```

These commands require the corresponding raster sidecars; the large upstream
products and pilot embedding matrix are local generated artifacts. Preserve the
source manifests, provenance sidecars, configuration, and output report when
reproducing a result. See [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for asset
preparation and [NASA_SCORECARD_METHODOLOGY.md](NASA_SCORECARD_METHODOLOGY.md)
for product assumptions. The verified Moon–Earth trace from PDS product
through terrain extraction, ranking, API, and UI is documented in the
[codebase guide](CODEBASE_GUIDE.md#moonearth-scorecard-moonmaretranquillitatis01).

# ENOM agent guide

## Project context

ENOM is a research prototype for exploring Earth environments that may be useful analogues for locations on the Moon or Mars. It contains related but distinct workflows for image retrieval, terrain comparison, evidence browsing, and experimental screening. Treat every result as a lead for investigation, not as validation of geological equivalence or mission suitability.

## Before changing code or data

- Read the relevant section of `docs/DEVELOPER_GUIDE.md` and consult `docs/ARCHITECTURE.md` for ownership and data flow. Read the focused methodology or data-source document when a change affects scientific meaning, inputs, or claims.
- Inspect the current worktree before editing. Preserve unrelated user changes and generated local data; do not reset, clean, or overwrite files just to simplify a task.
- Prefer the smallest change that follows the existing module boundaries. Keep provider-specific acquisition and decoding in scripts or adapters, domain logic in `src/twinworld/`, HTTP behavior in `api.py`, and presentation in `apps/twinworld/`.
- Do not invent scientific assumptions, thresholds, source coverage, validation results, or provenance. If evidence is missing, represent it as missing or unavailable and explain the limitation.

## Scientific and data integrity

- Keep image similarity, terrain similarity, contextual evidence, and mission screening distinct. Do not imply that image similarity establishes physical similarity, that a map or remote-sensing clue is a field measurement, or that a terrain proxy proves operational safety.
- Missing, unsupported, interpolated, or incompatible observations are not zero. Preserve availability and support information, and exclude values that do not satisfy the comparison's unit and spatial-scale requirements.
- Preserve the source coordinate reference, body-specific coordinate convention, units, native resolution, spatial and temporal support, nodata meaning, processing steps, and source identifiers/URLs. Record these in manifests or provenance sidecars as appropriate.
- Use projected grids with known linear units for metric terrain calculations. Keep observation values separate from masks, counts, and interpolation-support layers.
- Never reorder manifest records independently of associated feature matrices and metadata. Regenerate and validate the artifacts together when their row identity changes.
- Do not commit credentials, access tokens, private URLs, downloaded source archives, or large generated rasters/model artifacts. Follow `.gitignore`, the data manifests, and `docs/REPRODUCIBILITY.md`.
- Treat catalogue membership as distinct from imagery or raster coverage. A place can have contextual records without belonging in an image index or having a usable terrain measurement.

## Implementation conventions

- Python requires 3.12+. Use `uv` and the checked-in `uv.lock`; avoid ad hoc dependency changes. Keep public API response shapes and the TypeScript types in `apps/twinworld/` aligned.
- Frontend dependencies are managed with npm and `apps/twinworld/package-lock.json`. Use `npm ci` for reproducible installation.
- Add or update focused tests for behavior changes, especially coordinate conversions, missing-data states, provenance, units, scale compatibility, and API/UI contract changes. Use small fixtures and mocked provider responses; tests should not depend on live data services unless the task explicitly requires that.
- Do not run tests, builds, or other verification unless the user asks for verification. When asked, report exactly which checks ran and their results; a local build or test is not scientific validation, device validation, or deployment acceptance.
- Do not silently change scientific outputs, benchmark inputs, checked-in data, or public API semantics. Make such changes traceable and update the relevant documentation and provenance.

## Common commands

Run from the repository root unless stated otherwise:

```sh
uv sync --locked --extra dev
uv run pytest -q
uv run ruff check .
uv run mypy src/twinworld
```

Frontend commands:

```sh
cd apps/twinworld
npm ci
npm run build
npm test
```

Optional extras are workflow-specific: `vision` for DINOv2 inference and `earthdata` for STAC-based data preparation. See `docs/DEVELOPER_GUIDE.md` and `docs/REPRODUCIBILITY.md` before regenerating scientific artifacts.

## Where to look

- `src/twinworld/`: Python domain logic, scientific processing, retrieval, scorecards, and FastAPI service.
- `apps/twinworld/`: React/TypeScript explorer and browser tests.
- `scripts/`: bounded data ingestion, preparation, and evaluation workflows.
- `configs/` and `data/manifests/`: workflow settings and source-backed records.
- `data/terrain/`, `data/patches/`, `artifacts/`: local/generated scientific assets; check their manifests and sidecars before use.
- `tests/`: Python regression tests.
- `docs/`: architecture, scientific methodology, data provenance, and reproducibility.

## Further guidance

- `docs/DEVELOPER_GUIDE.md` — common development and data-integration workflows.
- `docs/ARCHITECTURE.md` and `docs/SCIENTIFIC_ARCHITECTURE.md` — module responsibilities, data flow, and scientific boundaries.
- `docs/DATA_SOURCE_REGISTRY.md` and `docs/DATA_SOURCES.md` — dataset products, provenance, coverage, and limitations.
- `docs/NASA_SCORECARD_METHODOLOGY.md` and `docs/MULTIMODAL_METHODOLOGY.md` — ranking definitions and assumptions.
- `docs/REPRODUCIBILITY.md` — setup and artifact regeneration.

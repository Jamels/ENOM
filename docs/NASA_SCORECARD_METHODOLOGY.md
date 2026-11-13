# NASA-first Moon–Earth terrain scorecard (initial slice)

## What this scorecard covers

The scorecard ranks the Copernicus DEM GLO-30 terrestrial terrain contexts already ingested by ENOM against one bounded lunar context near Mare Tranquillitatis. It is an analogue-discovery aid, not a landing-site recommendation, a geological equivalence result, or a globally exhaustive search. The React scorecard is served by the existing FastAPI service.

The checked-in/saved demo context is centred on 31.4°E, 8.5°N, with a 22×22 cell footprint of about 10.19 km. The NASA crop is extracted from LOLA `LDEM_64`, then reprojected to 463.0577 m cells to match ENOM's Copernicus/MOLA context grid. At this latitude, the LOLA source posting is about 473.8 m north–south and approximately 468.6 m east–west. Terrain features use local slope, local relief and roughness; absolute lunar radius/elevation is not compared with Earth elevation.

## NASA product inspected and accessed

- **Product:** LRO LOLA Gridded Data Record (GDR), `LDEM_64`, PDS dataset `LRO-L-LOLA-4-GDR-V1.0`, PDS3 product version V3.1.
- **Product label:** <https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/DATA/LOLA_GDR/CYLINDRICAL/IMG/ldem_64.lbl>
- **Binary image:** <https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/DATA/LOLA_GDR/CYLINDRICAL/IMG/ldem_64.img>
- **Definition read from the PDS label:** 11,520 lines × 23,040 samples; 64 pixels/degree; 16-bit little-endian integer DN; 0.5 m scale; 1,737,400 m reference-radius offset; 473.802 m/pixel at the equator; simple cylindrical/equirectangular projection, east-positive longitude, central meridian 180°. The label gives data coverage from 2009-07-13 through 2016-11-29 and product creation date 2019-03-15.
- **Access:** the adapter sends an HTTP `Range` request for only the enclosing crop rows and extracts the local samples. It rejects servers that ignore the range or return the wrong byte interval. The current retrieval used a small byte interval (roughly 1.5 MB), not the 530,841,600-byte global image.
- **Interpretation:** this is a gridded **shape/radius** map. Multiplying DN by 0.5 m produces height relative to the reference radius; the constant reference-radius offset is irrelevant to local derivatives. The label declares a product minimum and maximum but no missing-value sentinel; the adapter validates samples against the label range and does not invent a fill code. The label says that surface interpolation was used to compensate for incomplete coverage in higher-resolution regions. This image has no per-pixel observation-confidence layer, so finite raster pixels do not prove direct-shot coverage. The scorecard reports direct observation coverage and feature uncertainty as unquantified.
- **Use and citation:** data are accessed from the NASA PDS Geosciences Node. Cite the specific PDS dataset/product and follow the archive's citation guidance. The scorecard links both image and label.

## Earth product

The Earth side uses the existing Copernicus DEM GLO-30 DSM contexts in `data/terrain/`. These are sourced from Planetary Computer STAC collection `cop-dem-glo-30`; each context sidecar records its exact STAC item URL, source resolution, processing CRS, output grid, context and processing method. These are surface models (vegetation/buildings can affect heights), not bare-earth terrain. Current ranking coverage is only the locally indexed contexts with a DEM sidecar and pilot manifest record. NASADEM (`NASADEM_HGT.001`, LP DAAC DOI `10.5067/MEASURES/NASADEM/NASADEM_HGT.001`) is documented as a possible future Earth-source adapter; it is not substituted into this operational example.

## Feature extraction and comparable scale

Both bodies are analyzed over a nominal 22×22 cell, approximately 10.19 km context at a 463.0577 m analysis posting. The lunar adapter converts the LOLA cylindrical grid into a local metric equirectangular CRS using the lunar reference radius and the site latitude, then bilinearly resamples onto the existing Earth analysis posting. This handles the first-order latitude effect on east–west distances. The small context limits, but does not eliminate, the local projection approximation.

The score uses four derived terrain variables:

| Variable | Units | Feature scale | Absolute-difference tolerance used by the ranking index |
|---|---:|---:|---:|
| Mean slope | degrees | 926.1 m (two-cell central difference) | 5° |
| 90th percentile slope | degrees | 926.1 m | 10° |
| Median 3×3 local relief | metres | 1,389.2 m | 60 m |
| Median 3×3 roughness | metres | 1,389.2 m | 20 m |

Only same-unit measurements with feature scales within 5% are eligible. Unknown values and scale mismatches are omitted; they do not count as dissimilar. For eligible variable `j`, the component score is `exp(-abs(Earth_j - Moon_j) / tolerance_j)`. The overall terrain index is the weighted mean of component scores, renormalizing over positive-weight variables that are actually available. It lies in `[0,1]`, but it is a transparent ranking index, **not** a probability or calibrated physical similarity. Data completeness is the count of eligible weighted variables divided by the requested positive-weight variables, kept separate from similarity.

Default weights are mission-oriented research priorities, not trained parameters:

| Objective | Mean slope | Slope P90 | Local relief | Roughness |
|---|---:|---:|---:|---:|
| Landing | 0.35 | 0.30 | 0.20 | 0.15 |
| Base construction | 0.20 | 0.15 | 0.35 | 0.30 |
| Rover mobility | 0.20 | 0.40 | 0.25 | 0.15 |

Users can adjust each weight from 0 to 1. Negative, non-finite, unknown-key and all-zero configurations are rejected. Component scores renormalize to the positive sum among comparable features.

## Mission screening is separate and provisional

The lunar target receives a separate, explicitly provisional terrain-only screening result:

- Landing: 90th percentile slope ≤10° and median 3×3 relief ≤60 m.
- Base construction: mean slope ≤5° and median 3×3 relief ≤40 m.
- Rover mobility: 90th percentile slope ≤15° and median 3×3 relief ≤100 m.

These thresholds are illustrative research assumptions used to make the UI distinguish a separate mission-criteria assessment from analogue similarity. They are not validated against a selected lander, habitat design, rover, hazard-detection system, or operational safety requirement. A provisional pass means only that the available coarse terrain metrics meet those configured cutoffs. It is not an engineering suitability finding. Earth candidate mission suitability remains **not assessed**: a terrestrial analogue's value as a test site needs separate site/access/safety and process-specific criteria.

## Current measured example

The NASA crop was retrieved on 2026-11-14 and processed locally. At the lunar analysis grid, this context has mean slope 1.985°, slope P90 4.556°, median 3×3 local relief 26.363 m, and median 3×3 roughness 2.321 m. Those are derived values, not direct instrument channels. Feature uncertainty is not quantified by the source image, and interpolation can affect the local terrain signal.

The API returns the actual ranked Earth observations and their measured values, differences, component scores, completeness, source product IDs and URLs. The demonstration ranking should be reproduced from `/api/scorecards/rank`, rather than copied into this document, because local DEM sidecars define the candidate catalogue.

## Remaining evidence gaps

- No per-pixel LOLA count/confidence is paired with this GDR crop; direct observation support is unknown.
- No LOLA slope/roughness error propagation has been implemented.
- Thermal, illumination, volatile, radiation, geological, mineralogical and surface-material evidence is absent.
- NASADEM is registered but not ingested; the Earth demonstration relies on existing Copernicus DSM contexts.
- The Earth ranking corpus is a small curated pilot, not a planetary-scale catalogue. Presence or absence in it does not define a new analogue.
- Mission criteria and score tolerances have not been validated through mission engineering review or independent analogue relevance labels.
- `moon-analogs.zip`, referenced as a teammate prototype in the objective, was not found in the workspace or searched attachment/download locations; no code from it has been inspected or reused.

## Reproduce locally on macOS

From the repository root:

```sh
uv sync --extra dev
uv run python scripts/ingest_lola_scorecard.py
uv run pytest -q
uv run uvicorn twinworld.api:app --reload
```

In another terminal:

```sh
cd apps/twinworld
npm ci
npm run dev
```

Open <http://127.0.0.1:5173> and choose **NASA scorecards**. The ingestion command requires network access to the PDS Geosciences Node. It downloads only the bounded LOLA byte range and writes the crop and JSON provenance sidecar under `data/terrain/`.

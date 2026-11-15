# NASA-first planetary–Earth terrain scorecard

## What this scorecard covers

The scorecard ranks the Copernicus DEM GLO-30 terrestrial terrain contexts already ingested by ENOM against bounded lunar LOLA and Mars MOLA contexts. It is an analogue-discovery aid, not a landing-site recommendation, a geological equivalence result, or a globally exhaustive search. The React scorecard is served by the existing FastAPI service.

The checked-in/saved demo context is centred on 31.4°E, 8.5°N, with a 22×22 cell footprint of about 10.19 km. The NASA crop is extracted from LOLA `LDEM_64`, then reprojected to 463.0577 m cells to match ENOM's Copernicus/MOLA context grid. At this latitude, the LOLA source posting is about 473.8 m north–south and approximately 468.6 m east–west. Terrain features use local slope, local relief and roughness; absolute lunar radius/elevation is not compared with Earth elevation.

## NASA product inspected and accessed

- **Product:** LRO LOLA Gridded Data Record (GDR), `LDEM_64`, PDS dataset `LRO-L-LOLA-4-GDR-V1.0`, PDS3 product version V3.1.
- **Product label:** <https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/DATA/LOLA_GDR/CYLINDRICAL/IMG/ldem_64.lbl>
- **Binary image:** <https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx/DATA/LOLA_GDR/CYLINDRICAL/IMG/ldem_64.img>
- **Definition read from the PDS label:** 11,520 lines × 23,040 samples; 64 pixels/degree; 16-bit little-endian integer DN; 0.5 m scale; 1,737,400 m reference-radius offset; 473.802 m/pixel at the equator; simple cylindrical/equirectangular projection, east-positive longitude, central meridian 180°. The label gives data coverage from 2009-07-13 through 2016-11-29 and product creation date 2019-03-15.
- **Access:** the adapter sends an HTTP `Range` request for only the enclosing crop rows and extracts the local samples. It rejects servers that ignore the range or return the wrong byte interval. The current retrieval used a small byte interval (roughly 1.5 MB), not the 530,841,600-byte global image.
- **Interpretation:** this is a gridded **shape/radius** map. Multiplying DN by 0.5 m produces height relative to the reference radius; the constant reference-radius offset is irrelevant to local derivatives. The label declares a product minimum and maximum but no missing-value sentinel; the adapter validates samples against the label range and does not invent a fill code. The label says that surface interpolation was used to compensate for incomplete coverage in higher-resolution regions. This image has no per-pixel observation-confidence layer, so finite raster pixels do not prove direct-shot coverage. The scorecard reports direct observation coverage and feature uncertainty as unquantified.
- **Use and citation:** data are accessed from the NASA PDS Geosciences Node. Cite the specific PDS dataset/product and follow the archive's citation guidance. The scorecard links both image and label.

## Lunar environmental evidence: LRO Diviner

`scripts/ingest_diviner_scorecard.py` reads a bounded crop from Diviner Level 3 product `DGDR_ST_CLC_CYL_20120114N_128_IMG`, dataset `LRO-L-DLRE-5-GDR-V1.0`, PDS3 V6.0. Its [PDS label](https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_gdr_l3/2012/cylindrical/img/dgdr_st_clc_cyl_20120114n_128_img.lbl) defines a 20,480×46,080 simple-cylindrical grid, planetocentric latitude, east-positive longitude, 128 pixels/degree (236.901 m/pixel at the equator), signed little-endian int16, `-32768` missing, and `DN × 0.02 K`. It describes the field as model-derived rock-free regolith surface temperature using nighttime Diviner channels 6–8, with local time 19:30–05:30, solar incidence above 90°, emission below 15°, and stated temperature/quality filters. The selected product label spans 2012-01-14 to 2012-02-10; its algorithm description says the contributing Diviner observations span 2009-07-05 to 2016-10-10. The label says most surfaces have only one observation and provides no per-pixel uncertainty or repeat-count layer.

The adapter downloads only the byte interval covering a 44×44 sample crop. At 8.5°N, 32.0°E in Mare Tranquillitatis, 1,531 of 1,936 cells are valid (79.1%); the measured median is 94.48 K (mean 94.62 K, P10–P90 93.82–95.48 K). It stores the raster and provenance sidecar under `data/terrain/`. The same site has an independently ingested LOLA crop for terrain ranking. Diviner evidence appears separately in the UI, is not used in terrain similarity or mission screening, and has no paired terrestrial thermal measurement. The percentage describes valid raster cells, not independent instrument observations. A Moon-only thermal observation is not evidence of an Earth analogue's matching thermal environment.

## Mars surface characterization: MGS TES thermal inertia

`scripts/ingest_tes_scorecard.py` retrieves bounded rows from the NASA PDS Geosciences Node product `GLOBAL_TI_NIGHT_2007` and its paired `GLOBAL_TI_MSK_NIGHT_2007` interpolation mask in dataset `MGS-M-TES-5-TIMAP-V1.0`. The [map label](https://pds-geosciences.wustl.edu/mgs/mgs-m-tes-5-timap-v1/mgst_9001/data/global_ti_night_2007.lbl) defines a 7,200×3,600 PDS3 image of big-endian signed 16-bit values, units J/(m²·K·√s), 20 pixels/degree and 2.96 km/pixel. Its simple cylindrical map uses planetocentric latitude, east-positive longitude and a 3,396 km spherical radius. The [mask label](https://pds-geosciences.wustl.edu/mgs/mgs-m-tes-5-timap-v1/mgst_9001/data/global_ti_msk_night_2007.lbl) states that zero marks map values infilled by interpolation; those cells are excluded. PDS documents the map range as 5–5,000 J/(m²·K·√s), with values outside that range not computed. The archive describes input observations selected from nightside or dayside data with surface temperatures between 160 and 400 K; this product is the derived nightside thermal-inertia map, not a surface-temperature raster. Contributing observations span February 1999–April 2004.

The real bounded crop is centered on the indexed Aeolis Mars context and covers 8×8 native cells (~23.69 km). Sixty-three of 64 cells are non-interpolated; median thermal inertia is 68 J/(m²·K·√s), mean 69.02, and P10–P90 is 40.2–95.8. The ~2.96 km map is much coarser than the ~463 m MOLA terrain context, and it is returned only as Mars environmental evidence. It does not enter terrain similarity or mission screening, and no matched terrestrial thermal-inertia data are integrated. This crop reports distribution of map cells, not uncertainty or independent TES observation counts.

Re-ingest the default bounded crop on macOS with `uv run python scripts/ingest_tes_scorecard.py`; custom coordinates can be supplied with `--longitude` and `--latitude` (east-positive degrees).

Reproduce this context with:

```sh
uv run python scripts/ingest_diviner_scorecard.py \
  --longitude 32.0 --latitude 8.5 \
  --output-id moon_mare_tranquillitatis_diviner_01
uv run python scripts/ingest_lola_scorecard.py \
  --longitude 32.0 --latitude 8.5 \
  --output-id moon_mare_tranquillitatis_diviner_01
```

## Mars product: MGS MOLA MEGDR

The Mars observations use NASA PDS Geosciences Node MOLA MEGDR MEG128 topography and the matching MEG128 count grid. Sidecars record each tile’s exact PDS4 product identifier and `.img` links; for example the Aeolis observation uses [`megt00n090hb`](https://pds-geosciences.wustl.edu/mgs/urn-nasa-pds-mgs_mola_topography_derived/meg128/megt00n090hb.xml) and its paired [`megc00n090hb` count product](https://pds-geosciences.wustl.edu/mgs/urn-nasa-pds-mgs_mola_topography_derived/meg128/megc00n090hb.xml). The archive’s [MEGDR documentation](https://pds-geosciences.wustl.edu/missions/mgs/megdr.html) describes the product family. MEG128 is posted at 128 pixels/degree (about 463.0577 m at the equator), in an east-positive equirectangular grid with central meridian 180° and areocentric latitude.

For each 22×22-cell context, the adapter masks bins whose paired count is zero and computes one terrain variable: maximum minus minimum observed-bin elevation (`elevation_range`) over a nominal 10.19 km footprint. The scorecard compares this regional-relief proxy only with Earth’s elevation range at the same footprint scale. It does not infer slope, local relief, roughness, or absolute planetary elevation from this product. Count support is reported independently: the existing examples commonly have only about 20–50% observed bins. Since unobserved/interpolated bins can contain real extrema, the range may understate full-footprint relief. This is sparse sampled evidence, not a complete DEM estimate. Existing MOLA sidecars have no local retrieval timestamp; new runs of `scripts/ingest_mola.py` record the retrieval time.

### Mars geology: USGS SIM 1083 regional map units

`scripts/ingest_mars_geology.py` downloads the public GIS ZIP for [USGS Geologic Map of Mars, SIM 1083](https://doi.org/10.5066/P9UGAC18), reads the `I1083_GeoUnits` polygon shapefile, and performs a point-in-polygon lookup for each indexed MOLA site. The release is marked CC0. Its [README](https://www.sciencebase.gov/catalog/file/get/65678461d34e17319ded0ac1?f=__disk__ff%2Fdc%2Fa6%2Fffdca6605404f9a397ba005fd8d20632b6b7445e) specifies Mars 2000 spherical geographic coordinates with a 3,396,190 m radius; ENOM east longitudes are normalized to the layer's −180° to 180° domain. Map scale is 1:25,000,000 from 65°S to 65°N and approximately 1:5,000,000 poleward of 60°. The polygon layer was digitized and renovated using a semi-controlled THEMIS daytime IR 100 m/pixel basemap; that basemap posting is not the effective geologic resolution.

Ten indexed MOLA sites resolve to one unit code each. For example, the Aeolis site maps to `Hpr`, and Mawrth Vallis maps to `Nplc`. The scorecard exposes these as categorical map codes with release provenance, not as mineral identifications or measured soil, resource, or engineering properties. This context is displayed separately and never enters terrain similarity or mission suitability. The point lookup preserves unmapped and boundary-ambiguous states instead of assigning a nearest polygon.

## Earth product

The existing Copernicus DEM GLO-30 DSM contexts in `data/terrain/` remain available as one Earth data source. They are sourced from Planetary Computer STAC collection `cop-dem-glo-30`; each context sidecar records its exact STAC item URL, source resolution, processing CRS, output grid, context and processing method. These are surface models (vegetation/buildings can affect heights), not bare-earth terrain. The API ranks each ingested Earth DEM product independently; Copernicus is retained and is never overwritten by NASADEM.

### NASADEM Earth candidate adapter

`scripts/ingest_nasadem_scorecard.py` adds an opt-in NASA Earthdata adapter for one indexed Earth location. NASADEM HGT is the merged void-filled 1 arc-second product: 3601×3601 big-endian signed 16-bit elevations in metres relative to the EGM96 geoid. The paired NUM layer distinguishes source classes (including SRTM, ASTER, PRISM, and interpolation); SWB marks water. The adapter applies SWB, resamples one selected one-degree tile to the indexed patch CRS and the same nominal 463.06 m / 10.19 km terrain grid, and records NUM class fractions over that local context. It does not label every HGT elevation as a direct SRTM measurement. The DEM remains a surface-height product; vegetation/building returns and source-dependent fills can affect the result.

NASA CMR identifies the exact tile from the Earth observation coordinate. For example, a point near 15.14°E, 24.74°S resolves to `NASADEM_HGT_s25e015`; CMR returns its [granule record](https://cmr.earthdata.nasa.gov/search/granules.json?short_name=NASADEM_HGT&version=001&bounding_box=15%2C-25%2C16%2C-24) and LP DAAC archive URL. NASA requires Earthdata Login for the granule download. Generate a user token in [Earthdata Login](https://urs.earthdata.nasa.gov/documentation/for_users/user_token), enter it into the shell without echoing it, and run:

```sh
read -s "EARTHDATA_TOKEN?Earthdata token: "; export EARTHDATA_TOKEN
uv run python scripts/ingest_nasadem_scorecard.py --observation earth_namib_barchan-01
unset EARTHDATA_TOKEN
```

Only the selected tile is downloaded, bounded by a 64 MiB guard and cached under ignored `data/raw/nasadem/`. Its scorecard sidecar is written beside the output raster. NASADEM product contexts are ranked separately from Copernicus, preventing measurements from different DEMs from being blended under one source label. An authenticated download through this individual scorecard adapter remains unverified in this checkout; CMR metadata lookup and the synthetic-raster adapter path are tested. Separately, the discovery index contains contexts built from locally available NASADEM archives, as described in [precomputed analogue discovery](AUTONOMOUS_DISCOVERY.md). Their presence does not verify a fresh authenticated download.

### NASA MODIS terrestrial thermal and albedo data

The selected LST product is Terra `MOD11A2.061`, the 1 km Integerized Sinusoidal 8-day Level-3 product. Its temperatures are averages of qualifying clear-sky daily LST retrievals, stored with a 0.02 K scale factor. A future adapter must use `LST_Night_1km` together with `QC_Night`, `Clear_sky_nights`, and `Night_view_time`; retain QA-qualified pixels, expose clear-sky support, and report the composite interval and local observation-time distribution. This is a thermal-infrared land-surface retrieval, not air temperature. The identified Namib granule is `MOD11A2.A2000049.h19v11.061.2020048120245`, available through [NASA CMR](https://cmr.earthdata.nasa.gov/search/granules.json?short_name=MOD11A2&version=061&bounding_box=15%2C-25%2C16%2C-24). The science HDF is in the protected LP DAAC bucket; a direct unauthenticated GET returned HTTP 401. CMR metadata remains publicly searchable, but this environment has no `EARTHDATA_TOKEN`, so no MODIS observation is integrated.

The selected albedo product is combined Terra+Aqua `MCD43A3.061`, at 500 m. It provides black-sky (directional hemispherical) and white-sky (bihemispherical) albedo. It is published daily but each estimate uses a moving 16-day input window weighted toward the ninth day. Any extraction must pair it with `MCD43A2.061` quality layers, preserve albedo type/band and window date, and avoid calling it a single-day observation. The NASA product guide documents the compositing behavior and derivation from BRDF parameters.

These remain Earth environmental context measurements. They are not numerically scored against Diviner's nighttime rock-free lunar regolith-temperature model: the physical quantities and temporal/observational conditions do not match. MODIS remains un-ingested pending Earthdata authentication and a QA-aware real-granule demonstration.

## Feature extraction and comparable scale

Both bodies are analyzed over a nominal 22×22 cell, approximately 10.19 km context at a 463.0577 m analysis posting. The lunar adapter converts the LOLA cylindrical grid into a local metric equirectangular CRS using the lunar reference radius and the site latitude, then bilinearly resamples onto the existing Earth analysis posting. This handles the first-order latitude effect on east–west distances. The small context limits, but does not eliminate, the local projection approximation.

The available feature set has five variables. LOLA contexts provide four local derivative features; MOLA contexts provide only `elevation_range`; Copernicus and NASADEM DEMs can provide the five extracted variables:

| Variable | Units | Feature scale | Absolute-difference tolerance used by the ranking index |
|---|---:|---:|---:|
| Mean slope | degrees | 926.1 m (two-cell central difference) | 5° |
| 90th percentile slope | degrees | 926.1 m | 10° |
| Median 3×3 local relief | metres | 1,389.2 m | 60 m |
| Median 3×3 roughness | metres | 1,389.2 m | 20 m |
| 10 km footprint relief range | metres | 10,187.3 m | 200 m |

Only measurements in the variable’s canonical units (metres or degrees as listed above), with feature scales within 5%, are eligible. Two matching but incorrect unit labels cannot enter the score or mission screen. Weights must be finite nonnegative numbers with a finite positive total; booleans and numeric strings are rejected by the scoring engine. Unknown values and scale mismatches are omitted; they do not count as dissimilar. For eligible variable `j`, the component score is `exp(-abs(Earth_j - reference_j) / tolerance_j)`. The overall terrain index is the weighted mean of component scores, renormalizing over positive-weight variables that are actually available. It lies in `[0,1]`, but it is a transparent ranking index, **not** a probability or calibrated physical similarity. Data completeness is the count of eligible weighted variables divided by the requested positive-weight variables, kept separate from similarity. Thus a MOLA comparison with the default five positive weights can have at most 20% feature completeness even when the range matches successfully; its ranking score still reflects that one feature and must be read together with completeness and MOLA count support.

Default weights are mission-oriented research priorities, not trained parameters:

| Objective | 10 km range | Mean slope | Slope P90 | Local relief | Roughness |
|---|---:|---:|---:|---:|---:|
| Landing | 0.20 | 0.28 | 0.24 | 0.16 | 0.12 |
| Base construction | 0.20 | 0.16 | 0.12 | 0.28 | 0.24 |
| Rover mobility | 0.20 | 0.16 | 0.32 | 0.20 | 0.12 |

Users can adjust each weight from 0 to 1. Negative, non-finite, unknown-key and all-zero configurations are rejected. Component scores renormalize to the positive sum among comparable features.

A measurement contributes only when its availability is `available`, its value and spatial scale are finite, and its scale is positive. A numeric value marked `not_observed`, `outside_coverage`, `processing_failed`, `inapplicable` or `uncertain` is retained as evidence metadata but excluded from similarity and mission screening. Invalid or missing measurements reduce completeness; they are never converted to zero.

## Mission screening is separate and provisional

Targets receive a separate, explicitly provisional terrain-only screening result. The current checks require local slope and relief, so MOLA-only sites correctly return `insufficient_data`:

- Landing: 90th percentile slope ≤10° and median 3×3 relief ≤60 m.
- Base construction: mean slope ≤5° and median 3×3 relief ≤40 m.
- Rover mobility: 90th percentile slope ≤15° and median 3×3 relief ≤100 m.

The limits are explicit research assumptions with source context exposed in the API and UI. The 10° landing slope is informed by a **draft** NASA VIPER effective-slope requirement; the 5° construction slope is only analogous to a preliminary notional NASA landing-pad requirement; and the 15° rover slope is only contextualized by a NASA test of one rover on loose sand. The 60 m, 40 m and 100 m relief limits have no selected vehicle/site engineering basis. All scorecard slopes use a roughly 926 m baseline (local relief uses 1.39 km) and therefore cannot establish compliance with lander-footprint or rover-contact requirements. Limits are not validated against the challenge's mission design, habitat, rover, hazard-detection system, or operational safety requirements. A provisional pass means only that available coarse terrain metrics meet the configured cutoffs. It is not an engineering suitability finding. Earth candidate mission suitability remains **not assessed**: a terrestrial analogue's value as a test site needs separate site/access/safety and process-specific criteria. References: [draft NASA VIPER technical information](https://assets.science.nasa.gov/content/dam/science/psd/lunar-science/documents/VIPER_Technical_Information_AFPP.pdf), [preliminary/notional lunar landing and launch pad constraints](https://ntrs.nasa.gov/api/citations/20205009125/downloads/Lunar%20Landing%20%26%20Launch%20Pads%20v1.pdf), and [NASA rover slope-climbing test record](https://ntrs.nasa.gov/citations/20180000349).

## Current measured example

The NASA crop was retrieved on 2026-11-14 and processed locally. At the lunar analysis grid, this context has mean slope 1.829°, slope P90 3.933°, median 3×3 local relief 26.363 m, and median 3×3 roughness 2.321 m. Those are derived values, not direct instrument channels. Slope summaries exclude the outer cell ring because NumPy uses one-sided differences there; this keeps the reported slope support consistent with the two-cell central-difference scale. Feature uncertainty is not quantified by the source image, and interpolation can affect the local terrain signal.

The API returns the actual ranked Earth observations and their measured values, differences, component scores, completeness, source product IDs and URLs. Reproduce the default Moon example with `uv run python scripts/run_scorecard_demo.py`; generate the MOLA Mars example with `uv run python scripts/run_scorecard_demo.py --site mars_aeolis_nondune-01`. The outputs are `reports/moon-earth-scorecard-demo.json` and `reports/mars-earth-scorecard-demo.json`. Rankings derive from the checked-in terrain sidecars and are not independent analogue validation.

## Remaining evidence gaps

### Reference prototype review

Inspected `/Users/noah/Downloads/moon-analogs.zip` as a reference, without importing its standalone Flask application or sample CSVs. Its useful interaction pattern is mission selection plus adjustable variable weights feeding a ranked Earth-candidate list and a side-by-side measurement breakdown. ENOM's existing React/FastAPI scorecard implements those behaviors with validated weights, measured per-variable differences, provenance, missing-data completeness, and separate mission screening. The prototype's weighted normalized-range similarity was not copied: it assumes every value exists and uses arbitrary variable ranges, while ENOM uses explicit scale matching and missing-data-aware scoring. The prototype's numeric and categorical CSV observations are all marked `sample`; none were treated as findings. Its category similarity matrix and `known_analog == no` “New candidate” label were also excluded—the latter conflicts with the requirement that novelty cannot be inferred from a curated list. Its two-map and radar-chart layout was reviewed; ENOM keeps its existing explorer and scorecard presentation rather than introducing a second app or comparing unlike/missing measurements on a normalized radar chart.

- No per-pixel LOLA count/confidence is paired with this GDR crop; direct observation support is unknown. MOLA observed-bin support is explicitly partial and sparse.
- No LOLA slope/roughness error propagation has been implemented.
- Diviner provides one Moon-only nighttime regolith-temperature context; TES provides one Mars-only derived thermal-inertia context. Neither has a matched Earth counterpart in the scorecard, and neither affects terrain similarity. Thermal quantities are not treated as interchangeable. A generalized USGS global geologic-map code is available at ten Mars sites, but detailed site geology, mineralogy, material properties, and lunar geologic mapping remain absent.
- NASADEM ingestion requires an Earthdata Login token and has not yet been run against an authenticated NASA granule in this checkout.
- The Earth ranking corpus is a small curated pilot, not a planetary-scale catalogue. Presence or absence in it does not define a new analogue.
- Mission criteria and score tolerances have not been validated through mission engineering review or independent analogue relevance labels.

## Reproduce locally on macOS

From the repository root:

```sh
uv sync --extra dev
uv run python scripts/ingest_lola_scorecard.py
uv run python scripts/ingest_mars_geology.py
uv run pytest -q
uv run uvicorn twinworld.api:app --reload
```

In another terminal:

```sh
cd apps/twinworld
npm ci
npm run dev
```

Open <http://127.0.0.1:5173> and choose **NASA scorecards**. LOLA ingestion requires network access to the PDS Geosciences Node and reads only the bounded crop. The optional NASADEM adapter requires an Earthdata Login user token in `EARTHDATA_TOKEN` and downloads one selected 1-degree tile. Terrain adapters write their raster and JSON provenance sidecar under `data/terrain/`; the Mars geology adapter caches its source archive under ignored `data/raw/` and writes point-classification sidecars under `data/geology/`.

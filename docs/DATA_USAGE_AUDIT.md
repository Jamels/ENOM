# ENOM Scientific Data Usage Audit

**Audit date:** 2026-11-14  
**Scope:** Read-only review of the checked-in ENOM source, manifests, imagery/raster assets, and sidecar metadata. No remote datasets were downloaded and implementation was not changed.

## Executive finding

ENOM is partly dataset-first today. The scorecard ranks Earth contexts against actual LOLA or MOLA DEM-derived terrain measurements and reports source/coverage context. Its ranking is independent of the optional visual embedding artifact. The separate pilot retrieval surface still ranks by image embeddings (or an exploratory equal-weight visual/terrain blend). Thermal products and USGS geology are exposed as supporting evidence; they do not influence either scientific scorecard ranking or mission screening.

The project has substantial imagery breadth (100 pilot patches, 50 Earth and 50 Mars), but narrow physical-measurement coverage: 10 Earth DEM contexts, 10 Mars MOLA contexts, and one unique lunar LOLA terrain location. Only a small subset of candidate sites has planetary measurement coverage. Consequently, displayed analogue rankings are local catalogue rankings, not global searches or validated analogue determinations.

## 1. Dataset inventory and implementation status

“Present” below means local assets or measurement sidecars are checked in. “Registered” means an adapter/registry entry exists without local ingested measurements. Dataset-wide nominal coverage must not be confused with ENOM’s indexed site coverage.

| Dataset / source | What it measures | Local implementation and coverage | Contribution to ranking / mission use |
|---|---|---|---|
| ESA Sentinel-2 L2A and NASA MRO CTX pilot imagery | Surface image reflectance/texture; CTX image appearance | **Present:** `pilot-100.jsonl` has 50 Earth Sentinel-2 and 50 Mars CTX observations. Local patch assets and provenance rows are indexed. | DINOv2 image embeddings drive visual cross-body retrieval. Images and embeddings do not enter the DEM scorecard. Imagery is supporting evidence in a scientific comparison, not a physical measurement. |
| DINOv2 embeddings | Learned, dimensionless image features | **Operational when artifact exists:** `api.py` loads the separately generated `.npy` matrix and checks model/preprocessing identity against metadata/config. | Exact cosine nearest-neighbour visual ranking. The API can use it alone or combine normalized visual similarity with terrain similarity at equal 0.5/0.5 weights. This combination is explicitly exploratory. |
| Copernicus DEM GLO-30 / Microsoft Planetary Computer | Earth digital surface model (DSM) elevation | **Present:** 10 local ~10.19 km contexts, each resampled to about 463.06 m. Contexts correspond to 10 selected Earth pilot regions. | All 10 are Earth candidates in the scientific scorecard. Derived elevation range, mean slope, slope P90, 3×3 local relief and roughness can contribute when the chosen reference has matching units/scales. |
| NASADEM HGT.001 + NUM/SWB / NASA LP DAAC | Earth merged elevation; NUM source-class and SWB water masks | **Adapter registered, no local sidecars/assets found.** Ingestion requires Earthdata authentication. | No current rank or mission contribution. The API can include it as a candidate if ingested. It is a potential complementary/independent Earth DEM, not current evidence. |
| MGS MOLA MEG128 topography + count grid / NASA PDS | Mars gridded median elevation relative to the areoid; count grid distinguishes observed from interpolated bins | **Present:** 10 Mars contexts, each 22×22 cells (~10.19 km); observed-bin fraction ranges from 19.8% to 50.0%. Zero-count cells are masked. | Supplies one terrain variable: observed-bin footprint elevation range. It can rank against Earth elevation range at matching footprint scale. No MOLA slope, P90, local-relief, or roughness is computed. In image retrieval, terrain eligibility also applies the configured minimum observed coverage (default 25%), excluding the lower-coverage sites. |
| LRO LOLA GDR `LDEM_64` / NASA PDS | Moon gridded shape/radius | **Present:** one unique Mare Tranquillitatis 22×22-cell terrain raster (~10.19 km), at ~463 m output spacing. The `LDEM_64` product is interpolated and has no direct-shot confidence layer in this implementation. | Five terrain variables are derived and can be compared to the 10 Earth DEM candidates. It is the only local lunar terrain reference. The sidecar named `moon_mare_tranquillitatis_diviner_01` duplicates the same LOLA terrain values/location under a second observation ID; it is not a second LOLA site. |
| LRO Diviner Level 3 nighttime rock-free regolith surface temperature / NASA PDS | Product-derived nighttime regolith temperature in K, not a direct in-situ temperature | **Present:** one ~10.37 km crop; 1,531/1,936 cells valid (79.1%). Valid-cell fraction does not represent independent observation count. | Environmental evidence only. Not paired with Earth thermal data and excluded from terrain scorecard and mission checks. It is attached by the suffixed lunar observation ID, which currently corresponds to the duplicate LOLA sidecar rather than the canonical LOLA observation ID. |
| MGS TES `GLOBAL_TI_NIGHT_2007` / NASA PDS | Derived Mars nightside thermal inertia, not temperature | **Present:** one ~23.69 km context at `mars_aeolis_nondune-01`; 63/64 map cells are un-interpolated per the paired mask. | Environmental evidence only; excluded from terrain ranking and mission checks. No matched Earth thermal-inertia product is integrated. Its scale is also larger than the ~10.19 km terrain footprint. |
| USGS SIM 1083 global Mars geologic map | Categorical regional geologic map-unit classification | **Present:** 10 mapped point classifications associated with the 10 MOLA contexts. | Context only; not a soil assay, mineral detection, or engineering property. Excluded from rank/suitability calculations. |
| USGS Unified Geologic Map of the Moon (Fortezzo et al. 2020) | Categorical mapped unit, age, and interpretation | **Present:** two sidecars for the same Mare Tranquillitatis location, both `Im2`; one uses the duplicate suffixed observation ID. | Context only; excluded from rank/suitability. Regional map interpretation is not local composition evidence. |
| HiRISE DTMs, Geoscience Australia geology, MODIS LST/albedo, and other sources listed in the registry | Potential higher-resolution Mars terrain, Earth geology/thermal/albedo and other environmental variables | **Registered or roadmap only:** no corresponding ingested assets/measurements in the audited local corpus. | No current ranking contribution. Do not present these as observations currently used by ENOM. |

The detailed source registry contains further provenance and product caveats in `docs/DATA_SOURCE_REGISTRY.md`; the table above was checked against actual code and local assets, not accepted from that registry alone.

## 2. Data flow: source to interface

### Pilot image retrieval

1. `data/manifests/pilot-100.jsonl` records image ID, body, source/provider, coordinates, native scale, CRS, class label/status, geographic group, checksum, and local path.
2. Local image patches are embedded by the DINOv2 workflow. The API loads the NumPy matrix and validates the recorded model revision, preprocessing ID, dimensions, and row order before using it.
3. `src/twinworld/retrieval.py` normalizes vectors and ranks opposite-body patches by cosine similarity.
4. `api.py` optionally computes terrain similarity from measurement sidecars. With `method=combined`, only terrain-eligible results are included in the blend; visual cosine is min-max normalized within this gallery and averaged equally with terrain similarity. This is a discovery heuristic, not calibrated scientific evidence.
5. The web UI displays candidate image, coordinates, and source, with terrain/provenance summaries where available.

### Scientific terrain scorecard

1. Source-specific ingestion scripts create bounded, local rasters and JSON sidecars. In the checked-in corpus, the active measurement paths are Copernicus GLO-30 for Earth, MOLA MEG128 for Mars, and LOLA LDEM_64 for the Moon. NASADEM’s adapter exists but has not populated this checkout.
2. `src/twinworld/terrain.py` derives six metrics from metric-projected DEM cells: footprint elevation range; mean and 90th-percentile slope; median 3×3 local relief; median 3×3 roughness; and median curvature. Each measurement includes units, nominal spatial scale, availability, provenance, and a textual uncertainty note. Source uncertainty is not numerically propagated.
3. MOLA has a separate path: the count grid masks interpolated bins and only observed-cell elevation range is produced. Its coverage fraction and warning are retained in the sidecar and scorecard UI.
4. `api.py::_rank_earth_contexts` selects only Earth Copernicus and NASADEM sidecars whose observation ID joins to an Earth pilot manifest record. `scorecards.py::compare_candidate` compares only equal-name variables with matching units and scales within 5%. Each match receives `exp(-absolute difference / tolerance)` and the weighted mean is renormalized over matched variables. Missing or incompatible variables are omitted from the score and counted in completeness.
5. `mission_suitability` applies separate, provisional terrain screens to the reference site. The UI presents the source, measurement matches, completeness, geology, and thermal evidence alongside the result. Earth candidate analogue-site “suitability” is explicitly `not_assessed`.

### Geological and thermal context

USGS point-in-polygon classifications and the Diviner/TES summaries are read from sidecars in `api.py`. Geology is attached as categorical evidence. Thermal sidecars are selected by `observation_id` and attached as environmental evidence. Neither is transformed into a rank feature or a mission criterion. The currently implemented flows therefore support contextual interpretation, not cross-body geologic/thermal scoring.

## 3. Which data actually changes a rank or mission result?

### Scientific scorecard

- **Earth candidate values:** currently 10 Copernicus contexts; no NASADEM candidates. Their five terrain metrics contribute only when a corresponding reference measurement is present and the unit/scale checks pass.
- **Mars reference:** MOLA contributes only `elevation_range`. Against the five-variable scorecard presets, this means one of five weighted variables is available; the score is renormalized to that one variable, and completeness reports the limited match. Mars mission checks requiring slope/local relief cannot be assessed from MOLA’s current feature set.
- **Moon reference:** LOLA contributes five rankable metrics (all except curvature, which is derived but not in `VARIABLES`). Those measurements can be compared to Earth terrain metrics subject to scale checks. The suffixed duplicate LOLA record can produce a second apparent Moon reference at the same location.
- **Mission suitability:** the Moon LOLA-derived metrics can drive the configured provisional landing/base/rover screens. MOLA has no slope or local-relief metrics, so checks are insufficient. These screens are not vehicle certification criteria. Earth candidate suitability as a field analogue is not calculated.
- **Not rank inputs:** Diviner, TES, USGS geology, labels, and imagery provenance do not contribute to scientific terrain ranking or mission suitability. Visual embeddings affect only the separate visual/combined retrieval endpoint.

### Visual retrieval

The visual endpoint can rank all opposite-body pilot patches using image embeddings. Optional terrain mode uses only common, scale-matched measurements and excludes locations below the minimum coverage threshold. Combined mode has a fixed equal-weight blend after gallery-relative visual normalization. This is the part of the product where visual evidence can dominate despite the dataset-first direction.

## 4. Coverage: where real measurements exist

| Measurement layer | Local indexed coverage |
|---|---|
| Pilot imagery | 50 Earth + 50 Mars patches; no lunar image observations in the pilot manifest. |
| Earth terrain DEM | 10 selected Earth sites with Copernicus GLO-30 contexts; not the full imagery gallery and not global coverage. |
| Mars terrain DEM | 10 selected Mars pilot sites with MOLA contexts; observed-cell support is partial (19.8–50.0%). |
| Moon terrain DEM | One unique Mare Tranquillitatis context from LOLA, represented by two IDs in the terrain sidecars. |
| Earth NASADEM | Zero local coverage records. |
| Moon Diviner | One local context; currently associated with the suffixed lunar ID. |
| Mars TES thermal inertia | One local context at Aeolis; joined to the Mars site ID. |
| Mars geology | 10 mapped locations in the current sidecars. |
| Lunar geology | One unique site duplicated under two IDs. |

The global source products cover far more territory than these site windows. API dataset coverage should be interpreted as indexed observations in this checkout, not the upstream mission’s global footprint.

## 5. Scientific limitations and data-quality findings

### Resolution and comparability

- Earth Copernicus is a DSM, while Mars MOLA is a low-resolution gridded altimetry product and lunar LOLA is an interpolated shape/radius map. Equal output cell spacing does not make the source products’ effective resolution, vertical error, sampling, or surface semantics equivalent.
- The active Earth/Moon derivative comparisons are based on ~463 m output cells and ~10.2 km context windows. Source imagery may have much finer native GSD; it must not imply terrain knowledge at image scale.
- Earth slope, local-relief, and roughness metrics are calculated from resampled DEMs. Their tolerance values are engineering-scale research choices, not instrument-error models or calibrated planetary thresholds.
- Mars MOLA’s observed-bin range is a sparse-support regional-relief proxy. It can miss unsampled extrema; it does not yield slope or roughness. A 25% observed-cell threshold is used for visual terrain eligibility, but scorecard candidate ranking does not apply the same gate.
- TES context spans ~23.7 km, versus ~10.2 km terrain windows; the UI’s contextual sidecar does not make these footprints directly comparable.

### Missingness and uncertainty

- Terrain measurement types contain an uncertainty object, but the DEM adapter generally provides a description only. It does not propagate source vertical uncertainty, interpolation uncertainty, geolocation uncertainty, or resampling effects to the output metrics.
- The scorecard avoids treating absent measurements as zero or automatically dissimilar: unavailable/incompatible variables are excluded and match completeness is reported. However, candidate ordering is primarily by the renormalized score; low completeness is not itself a ranking penalty, so a one-variable Mars comparison can sit beside a five-variable Moon comparison without equivalent evidence breadth.
- MOLA count data are handled explicitly. LOLA’s valid raster cells cannot be interpreted as direct-shot coverage. Diviner valid raster cells are not counts of independent observations; most cells have limited repeat observations. TES uses a paired interpolation mask.
- NASADEM’s code retains source-class and water information but none of that is currently represented in local score outputs because the dataset has not been ingested.
- `terrain_features` masks incomplete neighborhoods for most local metrics and rejects geographic-degree rasters, but elevation range uses every valid cell and no propagated uncertainty. Curvature is calculated but is not an allowed score variable.

### Index joins and duplicated coverage

- The two LOLA sidecars for `moon_mare_tranquillitatis_01` and `moon_mare_tranquillitatis_diviner_01` point to the same site/raster measurements. The second ID exists to join the Diviner and lunar geology sidecars, which use that suffixed ID. As a result, the scorecard site enumeration can expose what appears to be two Moon terrain references although there is one physical location. This is a data-identity/join issue, not two independent measurements.
- The pilot image search represents geology evidence as `not_observed` rather than joining the available USGS site classifications to the corresponding pilot image observations. The scorecard path does attach geology. Thus the map data are locally present but are not consistently joined across product surfaces.
- Source registry entries may say operational while API registry state is based on sidecar-file counts; consumers should inspect observation IDs and measurement records, not only the badge.

### Suitability scope

Current “mission suitability” means provisional terrain-only screening of the planetary reference site. It omits thermal environment, illumination, volatile access, radiation, local material properties, hazards below DEM scale, vehicle-specific wheel/lander geometry, and mission operations. Threshold notes themselves acknowledge that some limits are assumptions or use different spatial scales from the cited engineering examples. Earth candidate sites are not screened for access, safety, land use, or field-test suitability.

## 6. Prioritised recommendations

1. **Fix site identity and evidence joins.** Use one canonical site ID for Mare Tranquillitatis and associate LOLA, Diviner, and USGS observations by stable site key plus product/observation ID. Ensure scorecard enumeration returns one site, while preserving separate product observations and their distinct spatial/temporal support.
2. **Make evidence breadth first-class in ranking.** Continue returning matched-variable count and completeness, and prevent one-variable and five-variable scores from appearing equally authoritative. Prefer a minimum-completeness eligibility rule or a transparent multi-axis ordering (similarity plus completeness); keep “no data” distinct from “poor match.”
3. **Bring measurement coverage up to the image catalogue.** Prioritize DEM contexts for more of the 100 pilot patches, especially sites intended for cross-body comparisons. Show the overlap count for each selected target and do not imply dataset coverage where only imagery exists.
4. **Complete and reconcile Earth DEM ingestion.** Ingest NASADEM where authorized and compare it to Copernicus at common footprints. Preserve NASADEM NUM source classes/SWB masks and report Copernicus DSM versus NASADEM merged elevation differences, rather than treating the products as interchangeable or silently combining them.
5. **Improve Mars topographic evidence.** Add an appropriately sourced higher-resolution Mars DTM/terrain product at selected sites where coverage permits. For MOLA-only sites, keep scorecard claims limited to observed-bin regional relief and avoid presenting slope-based mission conclusions as measured.
6. **Pair thermal variables across bodies before using them in ranking.** TES thermal inertia and Diviner temperature are different physical quantities and cannot be compared directly. Add matching, quality-screened Earth thermal products and choose a scientifically justified common variable/temporal aggregation. Keep temperature, thermal inertia, acquisition interval, local time, and valid-support fraction separate.
7. **Represent uncertainty quantitatively and propagate it.** Carry source product uncertainty/confidence, count/support, interpolation flags, vertical datum, and resampling method into derived-feature uncertainty. Where a product has no uncertainty layer, report that as unquantified and avoid confidence-like interpretation of the similarity score.
8. **Separate visual discovery from scientific evidence in product defaults.** Keep visual search clearly identified as an image-discovery mode. For any combined mode, expose each component, its calibration status, eligibility rule, and evidence completeness; do not label it a scientific or mission ranking.
9. **Connect geology consistently and constrain its meaning.** Join existing USGS map classifications to both scorecard and relevant pilot observations, expose map scale/unit descriptions, and keep generalized mapped units distinct from local mineralogy, regolith composition, or engineering properties.
10. **Close the unused-feature gap.** Either document curvature as a non-scored diagnostic or remove it from claims about scorecard inputs. For every registered dataset, expose separate states for registered, ingested, joined, and score-active so a source listing cannot be mistaken for used evidence.

## Audit evidence in code and data

- Source adapters: `scripts/ingest_copdem.py`, `scripts/ingest_nasadem_scorecard.py`, `scripts/ingest_mola.py`, `scripts/ingest_lola_scorecard.py`, `scripts/ingest_diviner_scorecard.py`, `scripts/ingest_tes_scorecard.py`, `scripts/ingest_mars_geology.py`, `scripts/ingest_lunar_geology.py`.
- Measurement/provenance model and DEM derivation: `src/twinworld/science.py`, `src/twinworld/terrain.py`.
- Score logic: `src/twinworld/scorecards.py`; API joins, coverage, retrieval, and Earth candidate selection: `src/twinworld/api.py`; visual nearest neighbours: `src/twinworld/retrieval.py`.
- Checked-in evidence: `data/manifests/pilot-100.jsonl`, `data/terrain/*.tif.json`, and `data/geology/*.json`.
- UI evidence: `apps/twinworld/src/components/DatasetsDialog.tsx`, `EarthAnalogueSidebar.tsx`, `ComparisonModal.tsx`, and the main app’s scorecard/site assembly.

This audit is a source-and-artifact review. It does not establish independent scientific validation of source products, derived metrics, analogue relevance, or mission thresholds.

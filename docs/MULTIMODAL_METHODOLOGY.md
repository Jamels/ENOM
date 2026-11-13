# Multimodal retrieval and comparison

## Retrieval available now

The implemented search takes a pilot observation ID and profile, selects records from the opposite planetary body, L2-normalizes the stored DINOv2 CLS vectors, and ranks exact cosine similarity with stable tie ordering. The response includes the metric and the model's discovery-only interpretation. The immutable model identity and embedding order are checked against the artifact metadata at load time.

## Terrain features

Copernicus GLO-30 is an Earth digital surface model, not a bare-earth terrain model. For one 2 km Namib image patch, a 10.19 km context is warped into the source patch's projected metric CRS on a 22×22 grid at 463.06 m spacing. The adapter reports full-context elevation range, mean slope at ~926 m support, and median local relief at ~1,389 m support. These features characterize broad context, not the 2 km image crop itself.

For the indexed Mars Meroe-region observation, the maintained PDS4 MOLA MEG128 tile and its count grid are read over the same 22×22 cell context. The PDS product has 463.06 m equatorial posting and stores interpolated values where no altimetry shot falls in a bin. In this selected context, 148/484 bins (30.6%) have observations. Empty bins are excluded, and only observed-bin elevation range is reported. This sampled range may miss unsampled local extrema; no Mars slope or local-relief estimate is returned.

The Earth and Mars contexts share the same grid posting and dimensions, so the API can expose a direct elevation-range difference with the MOLA sampling caveat. This single pair is exploratory comparison evidence, not retrieval calibration. Terrain values remain **outside ranking**: there is one context per body and the Mars altimetry is sparse. A terrain-only or combined ranking would not have a representative candidate gallery.

## Missingness and scale

Availability distinguishes available, not observed, outside coverage, processing failure, inapplicable and uncertain. Missing values are never coerced to zero. Measurements include a characteristic spatial scale and provenance. Cross-sensor pixel values and embedding coordinates are not treated as common physical variables. Raster comparisons at incompatible support scales are not fused.

## Evaluation boundary

No reviewed relevance judgements are present. The earlier pilot report is engineering evidence and provisional-label analysis, not an analogue-discovery benchmark. This phase therefore reports no precision/recall/NDCG improvement claim and no ablation result. The next evaluation requires a reviewed query/gallery judgement set with geographic/source-group holdouts, then paired visual, terrain, combined and geology-aware runs on identical queries.
# Phase 0.5 terrain retrieval

The indexed terrain observations are stored as georeferenced rasters with JSON provenance sidecars in `data/terrain/`. Copernicus GLO-30 Earth DSM contexts are warped to metric local-projection grids; MOLA MEG128 Mars contexts retain the Mars equirectangular grid using a 3,396 km reference radius. The MOLA count raster masks interpolated or unobserved bins.

Feature extraction reports elevation range, mean and 90th-percentile slope, 3×3 local relief, 3×3 roughness, and a finite-difference Laplacian curvature where the DEM support permits. Distances are derived from projected grid spacing. Absolute Earth and Mars elevations are never compared. MOLA currently supports elevation range only because sparse observed bins do not support stable derivative features.

The API requires a common measurement name and units, plus physical support scales within 5%. Pairwise terrain distance is the absolute feature difference divided by 1.4826 times the median absolute deviation across indexed observations for that feature; similarity is `exp(-mean(distance))`. This provides a transparent dimensionless ranking signal, not a calibrated probability or geological equivalence score.

`TWINWORLD_MIN_TERRAIN_COVERAGE` configures the minimum observed-cell fraction for terrain eligibility (default `0.25`, allowed range `0`–`1`). This is an engineering quality gate, not a scientifically established universal threshold. Missing or below-threshold terrain is omitted from terrain scoring and reported as unavailable. Combined mode averages per-query min-max normalized visual cosine and terrain similarity with equal weights; this provisional choice is explicit and should be evaluated against independent relevance judgments before scientific use.

## Current Phase 0.5 implementation note

The current API now exposes terrain-only and combined retrieval when the query and candidate pass the configured coverage threshold and share compatible measurement names, units, and physical scales. This is a prototype ranking policy, not validated scientific evidence: the pilot has no independently reviewed relevance labels, and available MOLA observations are sparse. The implementation and its current coverage are summarized in `reports/phase-05-evaluation.md`; no accuracy claim should be inferred from its rank/latency demonstration.

## Lunar readiness

The separate Moon–Earth scorecard currently uses one bounded cylindrical PDS3 LOLA `LDEM_64` crop around Mare Tranquillitatis. Its GDR surface interpolation means direct-shot coverage is not quantified; scorecard measurements carry that limitation. This is not a south-polar DEM. Global cylindrical and high-resolution polar stereographic products have different resolutions and semantics. Future polar ingestion must preserve count/uncertainty layers, product labels, reference radius, body-fixed frame/ephemeris, map projection, scaling, fill values, and pixel registration. No lunar image search or polar LOLA layer is available in the explorer.

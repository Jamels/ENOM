# Phase 0.4 evaluation

## Scope and result

The app executes real cross-body exact DINOv2 retrieval across the 100-record pilot and exposes scale-matched terrain contexts for one Earth/Mars region pair: Copernicus GLO-30 and MOLA MEG128 plus the MOLA count grid. The comparison API returns a raw elevation-range difference with an explicit sampling caveat.

## Ranking comparison

| Method | Indexed evidence | Quantitative relevance result |
|---|---|---|
| Visual only | 100 precomputed DINOv2 vectors | Not measured in this phase; no reviewed relevance judgments |
| Terrain only | One scale-matched Earth/Mars pair; MOLA has 30.6% observed bins | Not a retrieval gallery; no relevance evaluation |
| Visual + terrain | 100 image vectors plus one measured terrain pair | Not evaluated as ranking fusion; the single pair cannot calibrate ranking |
| Visual + terrain + geology | No geology observations | Not computable |

No claim is made that extra data improves ranking. The API uses visual ranking only and surfaces terrain measurements when the returned location is covered. Existing provisional class labels are not used as relevance judgments. At the paired 10.19 km scale, the Earth DSM range is 175.65 m; MOLA observed-bin range is 165 m from 148/484 populated cells. The 10.65 m difference is a descriptive measurement comparison and may be affected by unsampled Mars extrema and differing surface products.

## Engineering observations

- DEM ingestion retrieved a ~30 m source DSM context through public STAC/COG access, resampled to a 22×22 grid at 463.06 m, and computed three scale-tagged metrics.
- PDS MOLA MEG128 and count rasters were ingested as a georeferenced Mars crop through bounded HTTP byte ranges; empty/interpolated cells were masked.
- DINOv2 model inference was not repeated locally; the existing index is reused.
- Retrieval latency and UI interaction latency have not been measured as a formal benchmark.

## Next experiment

Expand MOLA/HiRISE DTM coverage to more Mars pilot regions (prefer HiRISE DTMs where scale permits), quantify terrain features at comparable support scales, and obtain blinded human pair relevance labels. Then compare identical query and gallery sets for visual, terrain, visual-plus-terrain, and available geology-aware rankings. Report retrieval metrics, evidence coverage, ranking stability, and changed candidate order separately.

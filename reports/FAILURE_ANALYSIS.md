# Failure analysis — current evidence log

## Retrieval failures

No retrieval evaluation has run, so there are no measured retrieval failures or ranked candidate cases to report. The two-image DINOv2 run is a pipeline smoke test only (details in `vertical-slice-smoke.md`). This file records observed data and evaluation risks without describing them as model outcomes.

## Observed source and methodology risks

| Observation | Evidence | Effect | Mitigation / cost |
|---|---|---|---|
| Mars CTX discovery returns raw EDR rather than map-projected products through the queried ODE instrument/product-type endpoint. | The first candidate label identifies `MRO-M-CTX-2-EDR-L0-V1.0`; the image is 14,336 × 5,056 and has no map-projection group in its attached header. | A rectangular pixel crop cannot yet be claimed to cover a precise metric footprint. | Use a map-projected CTX mosaic with source-seam provenance, or perform camera-model/DEM orthorectification. This adds substantial geospatial processing and may require terrain data. |
| Earth STAC search returns adjacent Sentinel-2 tiles from one overpass. | Five Namib items share one acquisition time and neighboring MGRS tiles. | Naive sample-level splitting can leak the same landform and illumination across train/test. | Group by connected feature and acquisition; choose geographically separated regions before patching. |
| Mars CTX ODE footprints around Nili Patera overlap and some product comments name the same dune field. | The first five results include “Dune field west of Meroe Patera” and “Nili Patera.” | Product rows are not independent sites; catalog comments are not human labels. | Cluster overlapping footprints into one geographic group and independently review patches before evaluation. |
| The Meroe CTX V01 seam map identifies the selected patch center as one source observation, but the surrounding mosaic is blended from multiple CTX observations. | Center resolves to `P02_002005_1865_XN_06N291W` (`DATA_QUAL=OK`, 2006-12-30); the crop source is the V01 map-projected mosaic. | A single center source ID does not prove every pixel in the 2 km crop comes from that observation. | Keep mosaic-tile provenance and center seam attribution distinct; inspect the seam map across the full crop before treating the patch as single-observation data. |
| NASA challenge Details/Resources tabs could not be retrieved through the available page/API path. | The accessible summary is available; the requested tab page returned an incomplete client-rendered document and the reader failed to fetch it. | Tab-specific source links and requirements remain unverified. | Revisit those tabs when accessible; do not infer requirements beyond the published summary. |
| The first 100-patch extraction accepted 74 patches and rejected 26 for source nodata/coverage below the 95% gate. | Remote `build_pilot.py` output: 5 Earth crops at Rub al Khali and 21 Mars crops had valid-source coverage below 0.95; several CTX crops fell within a catalog raster bounding box but outside its valid-data footprint. | The 100-row plan is not yet a 100-image dataset; planned bounds alone do not establish valid image coverage. | A repair pass searches for nearby valid pixels, checks dune patches against MGD3 polygons, and selects replacement fields only with valid CTX coverage. That repair pass was started but its completion is unverified because `n-pc-unix` went offline. |

## Required before model claims

- Acquire and georeference source patches from both bodies.
- Validate source identity, GSD, physical extent, and checksums.
- Obtain independent labels and complete relevance judgements for held-out queries.
- Run all methods on the same geographic holdouts and inspect real false matches.
- Resume the repair/extraction on `n-pc-unix`, then verify the 100-patch manifest, image checksums, valid-pixel fractions, class counts, and annotation CSV before benchmarking.

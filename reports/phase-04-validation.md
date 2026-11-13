# Phase 0.4 validation

## Verified in this checkout

- The source-backed pilot manifest contains 100 Earth/Mars observations, with matching ordered DINOv2 vectors copied from the already-completed remote GPU run.
- A real public Planetary Computer STAC search returned Copernicus item `Copernicus_DSM_COG_10_S25_00_E015_00_DEM`; its COG was read and warped to a 22×22 projected metric context at 463.06 m posting around `earth_namib_barchan-01`.
- A bounded PDS4 MOLA MEG128 range request retrieved the aligned Mars topography/count context around `mars-dune-barchan_crescent_dune-0067+071`. The raw product is big-endian signed 16-bit topography; the companion byte count raster was parsed separately. Raster coordinates use the Mars 3,396 km reference radius and 180° central meridian.
- Earth context elevation range is 175.65 m. The MOLA observed-bin range is 165 m from 148/484 bins (30.6%). The 10.65 m Earth-minus-Mars difference is exposed with the sampling caveat and does not indicate validated equivalence.
- API responses distinguish both terrain-covered observations from missing coverage, expose the scale-matched numeric difference, and preserve source links.
- The UI is wired to API data and displays the true pilot images and rankings.

## Not validated

- No independent reference surface or published terrain values were used to validate the DEM-derived feature values. Synthetic plane tests validate the feature calculation only.
- MOLA is a sparse gridded observation in this 10.19 km context: 69.4% of cells are empty and interpolated product values were masked. The observed-bin elevation range can miss unsampled extrema. This is insufficient for a calibrated terrain retrieval score.
- No reviewed relevance judgments exist. Visual similarity is not benchmarked as geological analogue relevance.
- No map base tiles, planetary mosaics, geology, mineralogy, thermal products, or lunar observations are integrated.
- The inherited DINOv2 embedding artifact was produced on `n-pc-unix`; no local CUDA task was run.

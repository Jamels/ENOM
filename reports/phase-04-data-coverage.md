# Phase 0.4 data coverage

Generated/checked 2026-11-05.

| Evidence | Earth | Mars | Moon |
|---|---:|---:|---:|
| Pilot imagery and precomputed DINOv2 embeddings | 50 observations | 50 observations | 0 |
| Copernicus DEM-derived terrain observations | 1 Namib context | 0 | 0 |
| MOLA MEG128 topography and count observations | 0 | 1 Meroe-region context | 0 |
| Geological map observations | 0 | 0 | 0 |
| Mineralogical / thermal / environmental observations | 0 | 0 | 0 |

The image counts come from the actual `pilot-100` manifest. The Copernicus context surrounds the 2 km Namib image patch and spans 10.19 km; it is sampled at 463.06 m to match the MOLA MEG128 context around Mars observation `mars-dune-barchan_crescent_dune-0067+071`. Product IDs, crop dimensions and processing parameters are in the `.tif.json` sidecars in `data/terrain/`. The MOLA count product records 148 observed bins out of 484 (30.6%); the remaining topography values are documented as interpolated and excluded from feature calculations. Lunar topography is not indexed. Counts refer to local app observations, not upstream product footprints.

The API reports Copernicus DEM GLO-30 as operational with one observation and reports terrain as unavailable elsewhere. The broader dataset families in `docs/DATA_SOURCE_REGISTRY.md` are not represented as live app data.

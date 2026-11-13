# Data sources and acquisition notes

This file is a source register, not a claim that imagery has already been acquired.

| Body / data | Candidate source | What it can support | Constraints to record |
|---|---|---|---|
| Earth multispectral imagery | [Microsoft Planetary Computer](https://planetarycomputer.microsoft.com/docs/) STAC; [Sentinel-2 L2A catalog](https://planetarycomputer.microsoft.com/catalog?filter=sentinel-2) | Discover and read public Sentinel-2 scenes; surface imagery at 10–60 m band-dependent native resolution | Collection/item ID, band(s), acquisition time, asset URL, processing level, CRS, native pixel size, signing/access rules, cloud cover |
| Earth harmonized imagery | [NASA/USGS HLS v2](https://planetarycomputer.microsoft.com/dataset/group/hls2) | Cross-sensor Landsat/Sentinel surface reflectance on a common 30 m grid | Product ID, provider granule, date, bands, grid, native sensor history; resampling/harmonization is not native resolution |
| Mars CTX | [NASA PDS Imaging Node](https://pds-imaging.jpl.nasa.gov/) and [CTX archive SIS](https://pds-imaging.jpl.nasa.gov/documentation/MRO_ctx_arch_sis.pdf) | Traceable MRO Context Camera products and labels | Product ID, observation geometry/date, label metadata, map projection, calibrated/derived level, native GSD, footprint; raw PDS formats may need specialized readers |
| Mars CTX mosaics | [Murray Lab CTX global mosaic](https://murray-lab.caltech.edu/CTX/V01/tiles/) | Broad discovery and candidate selection; the V01 mosaic is a 5 m/pixel global product built from CTX observations | Tiles can be very large (hundreds of MB to GB); mosaic version, contributing observations, seam/resampling history, coordinate reference system, local GSD; preserve constituent observation provenance rather than treating tile location as product provenance |
| Terrain | [NASADEM](https://lpdaac.usgs.gov/products/nasadem_hgtv001/) / [Copernicus DEM](https://dataspace.copernicus.eu/) for Earth; [MOLA](https://pds-geosciences.wustl.edu/missions/mgs/) and selected HiRISE DTMs for Mars | Independent relief, slope, and context evidence where coverage/resolution are adequate | Product/version, vertical datum, grid size, uncertainty, missing-data handling, spatial alignment |
| Planetary geology | [USGS Astrogeology](https://astrogeology.usgs.gov/) mapping and data products | Context and mapped units, not pixel-level ground truth by default | Map scale, compilation sources, mapping uncertainty, coordinate system |

## Acquisition policy

1. Discover and record candidate source items before downloading.
2. Select source observations and geographic groups before generating patches to limit spatial leakage.
3. Keep source products immutable; generated chips receive their own IDs and checksums.
4. Record exact asset URLs and retrieval timestamps in the manifest. Do not commit credentials or expiring signed URLs; retain stable item identifiers and public landing-page URLs instead.
5. Save provider-native metadata and processing history. For mosaics, preserve per-patch provenance to contributing observations when available.
6. Do not mark a source “verified” merely because its image can be opened.

## Current acquisition status

Source discovery was exercised on 2026-11-04. A Sentinel-2 STAC search for the Namib Desert bounding box (14–16°E, 23–25°S; 2024; cloud cover ≤20%) returned five adjacent tile items for the same acquisition time. A Mars ODE footprint query around Nili Patera (65–70°E, 7–10°N) returned CTX products; the first five include metadata comments “Dune field west of Meroe Patera” and “Nili Patera,” with ODE map-scale values around 5.4–5.6 m/pixel. The returned candidate list is saved in `data/manifests/candidate-sources.json`.

This is discovery evidence only. Adjacent Earth tiles are not independent samples, CTX comments are not independent annotations, and no patch has yet been generated or human-reviewed. A 32 KB HTTP range read of the first CTX candidate’s PDS3 label confirmed that the product is MRO CTX EDR (`MRO-M-CTX-2-EDR-L0-V1.0`), 14,336 lines × 5,056 samples, unsigned 8-bit. It is an unprojected observation; ODE’s map-scale value is retained separately and is not asserted as native GSD. Orthorectification or a map-projected mosaic is required before treating a Mars crop as a metric geospatial patch. The five Mars products have overlapping geographic footprints and must be grouped together for any split. No 1,000-sample feasibility claim has been made.

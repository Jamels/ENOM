# TwinWorld scientific architecture (Phase 0.5)

## Current implementation boundary

The application contains a FastAPI API over a 100-record Earth/Mars image pilot, an identity-checked DINOv2-small 384-D index, a React/TypeScript explorer, and indexed Copernicus DEM and MOLA terrain sidecars. The API supports visual, terrain-only, and combined ranking; terrain eligibility requires configured support coverage plus common measurements with matching units and near-matched physical scale. MOLA count grids distinguish shot-supported cells from interpolated DEM values. Rankings are discovery signals, not validated analogue claims.

A separate JSON catalogue contains sourced lunar, Mars, and terrestrial candidate locations independent of raster coverage. `science.py` defines body, availability, measurement, provenance, evidence, and comparison records. `lunar.py` defines longitude/latitude conventions, LOLA product semantics, and generic lunar polar CRS helpers. A separate Moon–Earth scorecard flow reads one bounded LDEM_64 terrain crop and compares it against indexed Earth DEM contexts; it does not add lunar image retrieval to the 100-image pilot.

## Layers

1. **Catalogue:** `PatchRecord` describes indexed image observations; `data/manifests/candidate-locations.json` describes candidate places and their sources without asserting data coverage.
2. **Ingestion:** Copernicus and MOLA scripts fetch bounded contexts for existing Earth/Mars pilot records. `scripts/ingest_lola_scorecard.py` reads a bounded PDS3 LOLA GDR crop for the separate scorecard and writes its provenance sidecar. Its current crop is near the equator and the global GDR does not provide quantified direct-shot support for that crop; do not conflate it with high-resolution south-polar LOLA products. Polar product ingestion is future work.
3. **Features:** Terrain measurement records carry units, support scale, uncertainty, and source provenance. Observed MOLA cells alone support its current elevation-range measurement.
4. **Retrieval/API:** Visual, terrain, and combined modes are distinct. Comparisons report supporting/contradictory evidence and data gaps. Profiles without implementing measurements remain unavailable.
5. **Explorer:** The browser presents the indexed Earth/Mars records, evidence, source links, result scores, and limitations. Its global equirectangular map is a locator, not a metric basemap.

## Coordinate policy

Earth patch longitudes use signed `[-180, 180)` values; pilot Mars manifests retain signed source longitude while the API returns normalized east-positive `[0, 360)` Mars values. Moon catalogue/scorecard coordinates use east-positive `[0, 360)`. Latitude is bounded to `[-90, 90]`. Planet radii are explicit in projection code. Lunar south-polar LOLA files have source-defined MOON_ME/ephemeris orientation; preserve native CRS and pixel-registration metadata rather than relabeling to the generic spherical helper CRS. Tests cover normalized longitudes, pole handling, and projected pole coordinates.

## Evidence semantics and limitations

Embedding cosine is a ranking metric, not physical similarity. Coverage absence is not a negative observation. Visual, terrain, evidence quality, and mission suitability must not be collapsed. Pilot labels and analogue pairs lack independent review, so the repository makes no retrieval-accuracy claim. MOLA's sparse bins may miss extrema; imagery differs in sensor, resolution, illumination, and processing. Unsupported objectives (including rover mobility and ancient-water inference) are not scientifically scored.

## Planned separately

- Ingest and validate high-resolution lunar south-polar LOLA elevation/count/uncertainty layers with preserved PDS metadata and native projections.
- Review an independent, blinded positive/negative relevance set before reporting metrics.
- Add body-aware basemaps only after CRS, tiling, attribution, and offline behavior are established; prioritize a frame-correct lunar polar view.
- Add mission-suitability evidence only from suitable traversability, illumination, thermal, resource, and hazard sources.

# Scientific architecture and constraints

See [ARCHITECTURE.md](ARCHITECTURE.md) for the current module map and data
flow. This page records the scientific conventions and boundaries that new
processing code must preserve.

## Coordinate policy

Earth patch longitudes use signed `[-180, 180)` values; pilot Mars manifests retain signed source longitude while the API returns normalized east-positive `[0, 360)` Mars values. Moon catalogue/scorecard coordinates use east-positive `[0, 360)`. Latitude is bounded to `[-90, 90]`. Planet radii are explicit in projection code. Lunar south-polar LOLA files have source-defined MOON_ME/ephemeris orientation; preserve native CRS and pixel-registration metadata rather than relabeling to the generic spherical helper CRS. Tests cover normalized longitudes, pole handling, and projected pole coordinates.

## Evidence semantics

Embedding cosine is a ranking metric, not physical similarity. Coverage absence is not a negative observation. Visual, terrain, evidence quality, and mission suitability must not be collapsed. Pilot labels and analogue pairs lack independent review, so the repository makes no retrieval-accuracy claim. MOLA's sparse bins may miss extrema; imagery differs in sensor, resolution, illumination, and processing. The image-retrieval profiles do not infer rover mobility or ancient-water evidence. The separate rover-mobility scorecard is a provisional terrain screen, not a validated mobility model; ancient-water inference remains unavailable.

## Research gaps

- Ingest and validate high-resolution lunar south-polar LOLA elevation/count/uncertainty layers with preserved PDS metadata and native projections.
- Review an independent, blinded positive/negative relevance set before reporting metrics.
- Add body-aware basemaps only after CRS, tiling, attribution, and offline behavior are established; prioritize a frame-correct lunar polar view.
- Add mission-suitability evidence only from suitable traversability, illumination, thermal, resource, and hazard sources.

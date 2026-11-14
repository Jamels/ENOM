# Verified scientific walkthroughs

This example traces a real repository observation through ranking and presentation. For the system map and routine development tasks, see the [architecture](ARCHITECTURE.md) and [developer guide](DEVELOPER_GUIDE.md). The score values are reproducible ranking outputs, not validated analogue claims.

## Verified Moon–Earth walkthrough

### Moon–Earth scorecard (`moon_mare_tranquillitatis_01`)

**Observation path:** [`scripts/ingest_lola_scorecard.py`](../scripts/ingest_lola_scorecard.py)
defines the PDS3 `LDEM_64` product and source label. Its `fetch_lola_crop(31.4,
8.5)` requests only the 32 × 32 signed 16-bit pixel window around the site,
checks the HTTP byte-range response, and converts digital numbers to metres
with the label's 0.5 m scale factor. `ingest()` builds the local lunar-radius
equirectangular CRS, bilinearly reprojects the crop to a 22 × 22 grid at
463.0577 m per cell, and writes the GeoTIFF plus a provenance sidecar. It then
calls [`terrain_features`](../src/twinworld/terrain.py), which derives six
DEM descriptors; the scorecard uses five and keeps curvature out of ranking.
LOLA's gridded product does not quantify direct-shot coverage, so the sidecar
and API report that uncertainty rather than treating all valid cells as direct
observations. The checked-in sidecar records all 484 output cells as valid.

1. **User Action (UI):** Switch to **NASA scorecards**, pick `MOON · Mare Tranquillitatis` (`31.4°E, 8.5°N`), objective `Landing-site terrain screening`, click **Rank Earth candidates** → `POST /api/scorecards/rank`.
2. **Backend Execution (`api.rank_scorecard`):**
   - In `main.tsx`, the scorecard view loads sites/config from `/api/scorecards/sites` and `/api/scorecards/config`; `runScorecard()` posts the selected site, objective and weights to `/api/scorecards/rank`.
   - `_scorecard_sites()` reads `data/terrain/moon_mare_tranquillitatis_01.tif.json`, which holds 5 LOLA `LDEM_64` measurements (`elevation_range = 532.919 m`, `mean_slope = 1.829°`, `slope_p90 = 3.933°`, `median_local_relief_3x3 = 26.363 m`, `median_roughness_3x3 = 2.321 m`). `validate_weights(request.weights)` checks that supplied weights are known, finite and non-negative (landing defaults: `0.20`, `0.28`, `0.24`, `0.16`, `0.12` in that variable order).
   - `mission_suitability()` evaluates the Moon site independently: `slope_p90 = 3.933° ≤ 10°` and `median_local_relief_3x3 = 26.363 m ≤ 60 m` → `provisional_pass`.
   - For each ingested Earth DEM sidecar (10 Copernicus GLO-30 contexts), `compare_candidate()` checks unit and 5% scale compatibility, then scores each variable as `sᵢ = exp(-|Moonᵢ − Earthᵢ| / toleranceᵢ)`. The final score is `Σ(wᵢsᵢ) / Σ(wᵢ)` over matched, positive-weight variables; completeness is matched variables divided by requested positive-weight variables. For top-ranked `earth_reykjanes_nondune-01`:
     - `elevation_range`: `exp(-|186.053 - 532.919| / 200) = 0.1765` (weight `0.20`)
     - `mean_slope`: `exp(-|1.483 - 1.829| / 5) = 0.9331` (weight `0.28`)
     - `slope_p90`: `exp(-|4.014 - 3.933| / 10) = 0.9920` (weight `0.24`)
     - `median_local_relief_3x3`: `exp(-|18.518 - 26.363| / 60) = 0.8774` (weight `0.16`)
     - `median_roughness_3x3`: `exp(-|2.565 - 2.321| / 20) = 0.9879` (weight `0.12`)
   - The Moon score is `0.793597` across `5/5` matched variables (`data_completeness = 1.0`); here the preset weights sum to 1, so the normalized weighted mean equals the weighted sum. For Mars MOLA site `mars_aeolis_nondune-01`, only `elevation_range` matches. The API divides that component's weighted value by its matched weight (`0.20`), giving `0.923361`, while completeness is `0.20` (`1/5`). That high score is based on one variable and is not evidence of a stronger match.

---


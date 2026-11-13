# Phase 0.5 evaluation

Generated from the indexed manifest and terrain sidecars by `scripts/run_phase05_evaluation.py`.

## Coverage and eligibility

- Imagery gallery: 100 observations (50 Earth, 50 Mars); each query exposes the same 50 cross-body candidates to all modes.
- Terrain contexts: 10 Copernicus GLO-30 Earth observations and 10 MOLA MEG128 Mars observations (20 observations across the indexed regions).
- Terrain quality threshold: at least 25% observed cells. Coverage below this configurable engineering threshold is excluded from terrain scoring.
- Terrain-eligible observations: 18/100; the remaining observations have no indexed terrain context or inadequate observed-cell coverage.
- Earth DEM valid-grid coverage is 100% for the selected contexts. MOLA observed-bin fractions range from 19.8% to 50.0%; two of ten MOLA contexts fall below the configured threshold.
- Terrain-only returns only candidates with at least one common same-unit feature at matching physical scale. Missing or low-coverage DEMs are never assigned a low similarity score.

## Mode measurements

Latency is measured around direct in-process search handler calls on this workstation; it excludes HTTP transport and visual browser rendering.

| Mode | Median latency (ms) | P95 latency (ms) |
|---|---:|---:|
| visual | 0.85 | 1.23 |
| terrain | 0.40 | 0.61 |
| combined | 0.51 | 0.62 |

Combined ranking used equal weighting after min-max normalization of visual cosine within each gallery and robust scaling of terrain feature differences. Paired rank changes compare combined and visual order within the terrain-eligible candidate subset. Across 62 returned combined candidates in the eight-query sample, changes ranged from -5 to +6 places.

## Scientific interpretation and limitations

- Visual-only retrieval remains the exact precomputed DINOv2 cosine ordering over the same cross-body gallery.
- Terrain-only and combined ranking now use measured elevation range when the physical context scales match within 5%; Earth morphology additionally records slope, slope percentile, local relief, roughness, and curvature where supported. MOLA's sparse support currently contributes elevation range only.
- Terrain feature differences are descriptive retrieval signals, not evidence of geological equivalence. Absolute elevations relative to Earth and Mars reference surfaces are never compared.
- A provisional qualitative spot check is not an independent relevance judgment. The pilot contains no reviewed relevance labels, so no retrieval-accuracy improvement is claimed. Cases where terrain changes the order are reported as ranking changes only, not as scientifically improved matches.
- Scientific plausibility of selected matches remains unvalidated; sensor, scale, illumination, geomorphic process, and data-product differences remain confounders. Human-reviewed, blinded relevance judgments are needed before effectiveness claims.
- No GPU inference was performed locally. The existing remote-produced DINOv2 embeddings were reused.

## API/UI validation state

See the Phase 0.5 validation report for automated checks and frontend build results.

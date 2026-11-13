# Benchmark methodology

## Experimental unit and scale

The unit is a georeferenced patch with immutable source observation, footprint, coordinate reference system, acquisition metadata, native ground sampling distance (GSD), and physical width/height. A selected physical scale (initially 2 km) is configuration, not a property inferred from pixel dimensions. Resampling changes the sampling grid and must never be described as increasing native resolution.

## Splits and leakage control

Assign groups by both source observation and geographic feature/region. All overlapping or adjacent patches from one feature stay in a single split. Keep a final geographic holdout untouched during descriptor or fusion-weight selection. A random patch split is invalid for the main generalization claim.

## Retrieval comparisons

Compare DINOv2-S/14, HOG plus a texture descriptor, a documented simple feature-fusion reranker, and a random-ranking baseline using the same query/gallery set and direction. Cache features keyed by image ID, source checksum, preprocessing configuration, and model checkpoint. Query and gallery are cross-planet by default. Exclude same-feature/overlapping pairs before scoring.

## Relevance and metrics

Report broad class agreement separately from independently reviewed morphological relevance. Compute Precision@1/5 only over reviewed candidates and show the reviewed denominator. Recall@k and mAP are reported only when the query’s relevant gallery is exhaustively judged. Report uncertain and unreviewed counts, per-class metrics, and geographic-group variation. The random baseline uses a fixed recorded seed.

## Robustness

Evaluate rotations, grayscale, controlled brightness/contrast, physical scale, crop shifts, and geographic holdouts as separate conditions. Record the source image and transform parameters. Report both metric changes and ranking stability; do not combine variants across train/test groups.

## Interpretation

Retrieval similarity is a discovery aid. A candidate pair is not a confirmed analogue until independent evidence (for example terrain shape, geological mapping, composition, or process measurements) is examined. Every case study records similarities, differences, missing evidence, uncertainty, and a concrete scientific use.

## Provenance and determinism

Every run records the config, software versions, model/checkpoint hash, ordered image IDs, split/group manifest, random seed, hardware, timings, and source checksums. Changes to preprocessing, checkpoint, or data produce a new artifact version.

The DINOv2-S/14 checkpoint is pinned to Hugging Face revision `ed25f3a31f01632728cabb09d1542f84ab7b0056` (resolved from the model API on 2026-11-04). The revision is required by the embedding function; no floating `main` revision is accepted.

## Current evidence state

The current indexed pilot has 100 Earth/Mars images and precomputed DINOv2-small embeddings. CUDA was used for an earlier artifact build, but is not required; inference device selection supports CUDA, Apple MPS, and CPU. A reproducible six-pair positive/negative review set is present in `configs/retrieval-review-set-v1.json`, but all pairs remain pending independent blinded review. No retrieval accuracy is reported. Phase 0.5 ranking behavior and evidence coverage are summarized in `reports/phase-05-evaluation.md`.

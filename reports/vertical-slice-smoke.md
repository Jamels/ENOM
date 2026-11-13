# Earth–Mars vertical-slice smoke run

**Run date:** 2026-11-04<br>
**Purpose:** verify source acquisition, metric patch generation, provenance capture, and CUDA embedding execution. This is not a retrieval benchmark.

## Inputs

| Body | Source | Patch | Native sampling | Status |
|---|---|---|---:|---|
| Earth | Sentinel-2 L2A item `S2B_MSIL2A_20241231T084259_R064_T33KWP_20241231T122915`, visual RGB COG | Namib, 15.7°E 24.0°S; 2 km square | 10 m | Label unknown; morphology not independently reviewed |
| Mars | Murray Lab CTX V01 tile `E068_N04`; center seam-map source `P02_002005_1865_XN_06N291W` | West of Meroe Patera; 68.0360°E 6.8121°N; 2 km square | 5 m | Seam-map source quality `OK`; label unknown; mosaic may blend sources |

Exact patch paths, checksums, and acquisition provenance are in `data/manifests/vertical-slice.jsonl`. The derived GeoTIFFs are retained locally under the ignored `data/patches/vertical-slice/` directory; source imagery and the full CTX tile remain on `n-pc-unix` under `data/raw/`.

## CUDA smoke result

- Host: `n-pc-unix`; NVIDIA GeForce RTX 3080, 10 GiB.
- Model: `facebook/dinov2-small`, immutable revision `ed25f3a31f01632728cabb09d1542f84ab7b0056`.
- Runtime: PyTorch `2.15.0+cu132`, Transformers `5.22.1`; inference device reported as `cuda`.
- Preprocessing: grayscale, 2nd–98th percentile stretch, RGB replication, 224 × 224 input.
- Output: finite, L2-normalized matrix of shape `2 × 384`; measured embedding pass 0.430 s, peak allocated VRAM 99,797,504 bytes.
- Machine-readable run metadata: `reports/vertical-slice-dinov2-smoke.json`.

The two-vector cosine similarity was 0.2283 in this smoke run. With one unreviewed patch per body, that number is only a pipeline diagnostic: it is not a relevance label, ranking metric, or evidence of analogue quality.

## Limits and next evidence needed

- Two images cannot support Precision@k, Recall@k, mAP, geographic holdouts, or a random baseline.
- The Earth and Mars labels remain `unknown`; visually inspecting the crops is not independent annotation.
- The Mars source ID is the seam-map observation at the patch center. The 2 km tile crop may cross seam boundaries; inspect the seam map over the full footprint before describing it as single-observation imagery.
- The imagery/embedding smoke path completed, but annotation, a larger candidate pool, duplicate/overlap filtering, and a reviewed cross-body relevance set remain prerequisites for retrieval evaluation.

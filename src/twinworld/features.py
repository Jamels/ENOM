"""Classical image descriptors and device selection for optional DINOv2."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
import rasterio
from skimage.color import rgb2gray
from skimage.feature import hog, local_binary_pattern
from skimage.transform import resize


def read_grayscale(path: Path, size: int = 224) -> np.ndarray:
    """Read the first band (or RGB) and resample to a fixed model grid."""
    with rasterio.open(path) as dataset:
        if dataset.count >= 3:
            image = np.stack([dataset.read(i) for i in (1, 2, 3)], axis=-1).astype(np.float32)
            valid = np.all(np.isfinite(image), axis=-1)
            if dataset.nodata is not None and np.isfinite(dataset.nodata):
                valid &= np.all(image != dataset.nodata, axis=-1)
            if not valid.any():
                raise ValueError(f"no valid pixels in {path}")
            low, high = np.percentile(image[valid], (2, 98))
            image = np.where(valid[..., None], image, low)
            image = np.clip((image - low) / max(float(high - low), 1e-6), 0, 1)
            gray = rgb2gray(image)
        else:
            image = dataset.read(1, masked=True).astype(np.float32).filled(np.nan)
            valid = np.isfinite(image)
            if not valid.any():
                raise ValueError(f"no valid pixels in {path}")
            low, high = np.nanpercentile(image, (2, 98))
            gray = np.clip((image - low) / max(float(high - low), 1e-6), 0, 1)
            gray = np.nan_to_num(gray, nan=0.0)
    return resize(gray, (size, size), anti_aliasing=True, preserve_range=True).astype(np.float32)


def classical_descriptor(path: Path, *, size: int = 224) -> np.ndarray:
    """Concatenate normalized HOG and rotation-sensitive LBP histograms."""
    gray = read_grayscale(path, size=size)
    hog_vector = hog(
        gray,
        orientations=9,
        pixels_per_cell=(16, 16),
        cells_per_block=(2, 2),
        feature_vector=True,
        channel_axis=None,
    )
    points, radius = 24, 3
    lbp_input = np.rint(np.clip(gray, 0, 1) * 255).astype(np.uint8)
    lbp = local_binary_pattern(lbp_input, points, radius, method="uniform")
    lbp_hist, _ = np.histogram(lbp, bins=np.arange(points + 3), range=(0, points + 2), density=True)
    vector = np.concatenate((hog_vector, lbp_hist.astype(np.float32)))
    norm = np.linalg.norm(vector)
    return vector / max(float(norm), 1e-12)


def select_device(preference: Literal["auto", "cpu", "cuda", "mps"] = "auto") -> str:
    """Choose an inference device. CUDA availability is queried only when this is called."""
    import torch

    if preference == "cpu":
        return "cpu"
    if preference == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is unavailable")
        return "cuda"
    if preference == "mps":
        if not torch.backends.mps.is_available():
            raise RuntimeError("MPS was requested but is unavailable")
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"

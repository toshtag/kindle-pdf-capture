"""Image normalisation: resize, white-background correction, sharpening, JPEG save.

All functions accept and return uint8 BGR ndarrays (OpenCV native format)
unless stated otherwise.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def normalize_image(bgr: np.ndarray, *, resize_width: int) -> np.ndarray:
    """Resize, whiten background, and sharpen a cropped page image.

    The width is fixed to *resize_width*; height scales proportionally.

    Args:
        bgr: uint8 BGR ndarray (OpenCV format).
        resize_width: Target width in pixels.

    Returns:
        Normalised uint8 BGR ndarray.
    """
    resized = _resize(bgr, resize_width)
    whitened = whiten_background(resized)
    return sharpen(whitened)


# ---------------------------------------------------------------------------
# Internal helpers (also exported for targeted testing)
# ---------------------------------------------------------------------------


def _resize(bgr: np.ndarray, target_width: int) -> np.ndarray:
    h, w = bgr.shape[:2]
    if w == target_width:
        return bgr
    scale = target_width / w
    new_h = round(h * scale)
    interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LANCZOS4
    return cv2.resize(bgr, (target_width, new_h), interpolation=interpolation)


def whiten_background(bgr: np.ndarray, *, threshold: int = 210) -> np.ndarray:
    """Push near-white pixels to pure white.

    Pixels with all channels >= *threshold* are set to 255.  Dark pixels
    (text, graphics) below the threshold are left untouched.

    Args:
        bgr: uint8 BGR ndarray.
        threshold: Minimum per-channel value for a pixel to be whitened.

    Returns:
        Corrected uint8 BGR ndarray (same shape).
    """
    result = bgr.copy()
    mask = np.all(result >= threshold, axis=2)
    result[mask] = 255
    return result


def sharpen(bgr: np.ndarray) -> np.ndarray:
    """Apply a mild unsharp mask to improve text legibility.

    Uses a Gaussian blur subtract approach (unsharp mask) with conservative
    parameters so thin strokes are enhanced without introducing artefacts.

    Args:
        bgr: uint8 BGR ndarray.

    Returns:
        Sharpened uint8 BGR ndarray (same shape and dtype).
    """
    blurred = cv2.GaussianBlur(bgr, (0, 0), sigmaX=1.5)
    # addWeighted: result = 1.4*src - 0.4*blur  (mild sharpening)
    sharpened = cv2.addWeighted(bgr, 1.4, blurred, -0.4, 0)
    return np.clip(sharpened, 0, 255).astype(np.uint8)


def save_jpeg(bgr: np.ndarray, path: Path, *, quality: int = 80) -> None:
    """Save a BGR ndarray as an optimised JPEG file.

    Uses Pillow (not cv2.imwrite) so that ``optimize=True`` and explicit
    subsampling control are available.

    Args:
        bgr: uint8 BGR ndarray.
        path: Destination file path.  Parent directories are created
            automatically if they do not exist.
        quality: JPEG quality (1-95; 75-85 recommended for this use case).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # OpenCV uses BGR; Pillow expects RGB
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(rgb)
    pil_img.save(
        path,
        format="JPEG",
        quality=quality,
        optimize=True,
        subsampling=2,  # 4:2:0 — good balance of size vs. quality
    )
    logger.debug("Saved JPEG: %s (quality=%d)", path, quality)

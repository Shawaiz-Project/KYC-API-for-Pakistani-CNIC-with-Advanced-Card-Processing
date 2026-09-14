from __future__ import annotations

import math
from typing import Any

from .model_registry import get_model_registry
from .normalization import normalize_text


def recognize_text(image, side: str) -> list[dict[str, Any]]:
    """Run the process-local EasyOCR baseline and retain every raw detection."""

    raw_results = get_model_registry().run_ocr(image)
    items: list[dict[str, Any]] = []
    for result in raw_results:
        if not isinstance(result, (list, tuple)) or len(result) < 3:
            continue
        raw_box, raw_text, raw_score = result[0], result[1], result[2]
        text = str(raw_text)
        if not text.strip():
            continue
        try:
            score = float(raw_score)
            if not math.isfinite(score):
                score = None
        except (TypeError, ValueError):
            score = None
        items.append(
            {
                "side": side,
                "raw_text": text,
                "normalized_text": normalize_text(text),
                "bbox": _json_box(raw_box),
                "confidence": {
                    "value": score,
                    "type": "raw_ocr_score",
                    "calibrated": False,
                },
            }
        )
    return items


def _json_box(raw_box) -> list[list[float]]:
    points: list[list[float]] = []
    try:
        for point in raw_box:
            if len(point) < 2:
                continue
            x, y = float(point[0]), float(point[1])
            if math.isfinite(x) and math.isfinite(y):
                points.append([round(x, 3), round(y, 3)])
    except (TypeError, ValueError):
        return []
    return points if len(points) == 4 else []

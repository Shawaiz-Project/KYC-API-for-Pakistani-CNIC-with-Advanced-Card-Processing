"""Unicode and geometry helpers for OCR output.

The helpers in this module intentionally have no OCR-library dependency.  They
accept EasyOCR-style tuples as well as the JSON-ready dictionaries emitted by
the detector service.  Raw OCR text and raw model scores are always retained;
normalization is exposed as a separate value and never changes the evidence.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from numbers import Real
import re
from statistics import median
import unicodedata
from typing import Any


_DIGIT_TRANSLATION = str.maketrans(
    {
        **{ord(chr(0x0660 + number)): str(number) for number in range(10)},
        **{ord(chr(0x06F0 + number)): str(number) for number in range(10)},
    }
)

# Directional controls affect display order, not the identity text itself.  OCR
# engines sometimes include them in recognized strings, so remove them from
# normalized values while leaving ``raw_text`` untouched.
_BIDI_CONTROLS = dict.fromkeys(
    map(
        ord,
        (
            "\u061c",  # Arabic letter mark
            "\u200e",  # left-to-right mark
            "\u200f",  # right-to-left mark
            "\u202a",
            "\u202b",
            "\u202c",
            "\u202d",
            "\u202e",
            "\u2066",
            "\u2067",
            "\u2068",
            "\u2069",
        ),
    ),
    None,
)

_HORIZONTAL_WHITESPACE = re.compile(r"[^\S\r\n]+", flags=re.UNICODE)
_ALL_WHITESPACE = re.compile(r"\s+", flags=re.UNICODE)


def normalize_unicode(value: Any, form: str = "NFC") -> str | None:
    """Return a canonical Unicode representation without guessing content.

    ``NFC`` preserves compatibility distinctions.  Callers that consume OCR
    text usually want ``NFKC`` so Arabic presentation forms and full-width
    punctuation are made comparable.  Both forms are explicitly supported.
    """

    if value is None:
        return None
    if form not in {"NFC", "NFKC"}:
        raise ValueError("Unicode normalization form must be NFC or NFKC.")
    return unicodedata.normalize(form, str(value))


def normalize_digits(value: Any) -> str | None:
    """Translate Arabic-Indic and Persian digits to ASCII digits."""

    text = normalize_unicode(value, "NFC")
    return None if text is None else text.translate(_DIGIT_TRANSLATION)


def normalize_text(
    value: Any,
    *,
    form: str = "NFKC",
    collapse_whitespace: bool = True,
    strip_bidi_controls: bool = True,
) -> str | None:
    """Normalize OCR text while preserving its actual recognized characters.

    This performs Unicode normalization, decimal digit normalization, removal
    of display-only bidi controls, and whitespace cleanup.  It deliberately
    does not perform OCR substitutions such as ``O`` -> ``0``.
    """

    text = normalize_unicode(value, form)
    if text is None:
        return None
    text = text.translate(_DIGIT_TRANSLATION)
    if strip_bidi_controls:
        text = text.translate(_BIDI_CONTROLS)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if collapse_whitespace:
        text = _ALL_WHITESPACE.sub(" ", text)
    else:
        text = _HORIZONTAL_WHITESPACE.sub(" ", text)
    return text.strip()


def contains_rtl_text(value: Any) -> bool:
    """Return whether text contains an Arabic/RTL-direction character."""

    text = "" if value is None else str(value)
    return any(unicodedata.bidirectional(char) in {"R", "AL", "AN"} for char in text)


def _point(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        return [float(value[0]), float(value[1])]
    except (TypeError, ValueError):
        return None


def normalize_bbox(value: Any) -> list[list[float]] | None:
    """Return a four-point polygon for common rectangle/polygon encodings."""

    if value is None:
        return None
    if isinstance(value, Mapping):
        keys = ("x_min", "y_min", "x_max", "y_max")
        if all(key in value for key in keys):
            value = [value[key] for key in keys]
        elif "points" in value:
            value = value["points"]

    if isinstance(value, (list, tuple)) and len(value) == 4 and all(
        isinstance(coordinate, Real) and not isinstance(coordinate, bool) for coordinate in value
    ):
        x_min, y_min, x_max, y_max = map(float, value)
        return [
            [x_min, y_min],
            [x_max, y_min],
            [x_max, y_max],
            [x_min, y_max],
        ]

    if isinstance(value, (list, tuple)):
        points = [_point(point) for point in value]
        points = [point for point in points if point is not None]
        if len(points) >= 4:
            return points[:4]
    return None


def bbox_bounds(value: Any) -> tuple[float, float, float, float] | None:
    """Return ``(x_min, y_min, x_max, y_max)`` for a supported bbox."""

    polygon = normalize_bbox(value)
    if polygon is None:
        return None
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    return min(xs), min(ys), max(xs), max(ys)


def union_bboxes(*values: Any) -> list[list[float]] | None:
    """Return the rectangular union of the supplied boxes."""

    bounds = [bbox_bounds(value) for value in values]
    bounds = [value for value in bounds if value is not None]
    if not bounds:
        return None
    x_min = min(value[0] for value in bounds)
    y_min = min(value[1] for value in bounds)
    x_max = max(value[2] for value in bounds)
    y_max = max(value[3] for value in bounds)
    return normalize_bbox([x_min, y_min, x_max, y_max])


def _normalize_confidence(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        raw_value = value.get("value")
    else:
        raw_value = value
    if isinstance(raw_value, Real) and not isinstance(raw_value, bool):
        raw_value = float(raw_value)
    elif raw_value is not None:
        try:
            raw_value = float(raw_value)
        except (TypeError, ValueError):
            raw_value = None
    if raw_value is None:
        return None
    return {
        "value": raw_value,
        "type": "raw_ocr_score",
        "calibrated": False,
    }


def coerce_ocr_item(item: Any, *, index: int = 0, side: str | None = None) -> dict[str, Any]:
    """Coerce an OCR item to the service's JSON-ready evidence shape.

    Preferred input shape::

        {
            "side": "front",
            "raw_text": "شناختی نمبر",
            "normalized_text": "شناختی نمبر",
            "bbox": [[x, y], [x, y], [x, y], [x, y]],
            "confidence": {
                "value": 0.91,
                "type": "raw_ocr_score",
                "calibrated": false,
            },
        }

    EasyOCR's ``(bbox, text, confidence)`` tuple is also accepted.
    """

    explicit_field = None
    label = None
    if isinstance(item, Mapping):
        raw_text = item.get("raw_text", item.get("text"))
        supplied_normalized = item.get("normalized_text")
        bbox = item.get("bbox", item.get("box"))
        confidence = item.get("confidence", item.get("raw_confidence"))
        resolved_side = item.get("side", side)
        explicit_field = item.get("field", item.get("field_name"))
        label = item.get("label")
    elif isinstance(item, (list, tuple)) and len(item) >= 2:
        bbox, raw_text = item[0], item[1]
        confidence = item[2] if len(item) >= 3 else None
        supplied_normalized = None
        resolved_side = side
    else:
        raise TypeError("OCR items must be mappings or (bbox, text, confidence) tuples.")

    raw_text = None if raw_text is None else str(raw_text)
    normalized = normalize_text(supplied_normalized if supplied_normalized is not None else raw_text)
    return {
        "side": None if resolved_side is None else str(resolved_side),
        "raw_text": raw_text,
        "normalized_text": normalized,
        "bbox": normalize_bbox(bbox),
        "confidence": _normalize_confidence(confidence),
        "source_index": int(index),
        "field": explicit_field,
        "label": label,
    }


def _line_direction(items: list[dict[str, Any]], direction: str) -> str:
    if direction != "auto":
        return direction
    return "rtl" if any(contains_rtl_text(item.get("normalized_text")) for item in items) else "ltr"


def order_ocr_items(
    items: Iterable[Any],
    *,
    direction: str = "auto",
    line_tolerance: float = 0.6,
    side: str | None = None,
) -> list[dict[str, Any]]:
    """Order OCR items top-to-bottom and in each line's reading direction.

    ``direction='auto'`` uses right-to-left ordering for a line containing Urdu
    or Arabic script and left-to-right ordering otherwise.  Use ``'rtl'`` to
    force Urdu visual-order reconstruction.
    """

    if direction not in {"auto", "ltr", "rtl"}:
        raise ValueError("direction must be auto, ltr, or rtl.")
    if line_tolerance <= 0:
        raise ValueError("line_tolerance must be positive.")

    normalized_items = [coerce_ocr_item(item, index=index, side=side) for index, item in enumerate(items)]
    positioned: list[tuple[dict[str, Any], tuple[float, float, float, float]]] = []
    unpositioned: list[dict[str, Any]] = []
    for item in normalized_items:
        bounds = bbox_bounds(item.get("bbox"))
        if bounds is None:
            unpositioned.append(item)
        else:
            positioned.append((item, bounds))

    if not positioned:
        return normalized_items

    heights = [max(1.0, bounds[3] - bounds[1]) for _, bounds in positioned]
    baseline_height = median(heights)
    positioned.sort(key=lambda pair: ((pair[1][1] + pair[1][3]) / 2.0, pair[1][0], pair[0]["source_index"]))

    lines: list[dict[str, Any]] = []
    for item, bounds in positioned:
        center_y = (bounds[1] + bounds[3]) / 2.0
        height = max(1.0, bounds[3] - bounds[1])
        best_line = None
        best_distance = None
        for line in lines:
            tolerance = line_tolerance * max(baseline_height, height, line["height"])
            distance = abs(center_y - line["center_y"])
            if distance <= tolerance and (best_distance is None or distance < best_distance):
                best_line = line
                best_distance = distance
        if best_line is None:
            lines.append({"items": [(item, bounds)], "center_y": center_y, "height": height})
        else:
            best_line["items"].append((item, bounds))
            count = len(best_line["items"])
            best_line["center_y"] = ((best_line["center_y"] * (count - 1)) + center_y) / count
            best_line["height"] = max(best_line["height"], height)

    lines.sort(key=lambda line: line["center_y"])
    ordered: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines):
        line_items = [pair[0] for pair in line["items"]]
        resolved_direction = _line_direction(line_items, direction)
        line["items"].sort(
            key=lambda pair: ((pair[1][0] + pair[1][2]) / 2.0, pair[0]["source_index"]),
            reverse=resolved_direction == "rtl",
        )
        for word_number, (item, _) in enumerate(line["items"]):
            item["line_index"] = line_number
            item["word_index"] = word_number
            ordered.append(item)

    # OCR results without geometry cannot be safely mixed into geometric line
    # order.  Preserve their engine order at the end rather than guessing.
    ordered.extend(sorted(unpositioned, key=lambda item: item["source_index"]))
    return ordered


def order_urdu_ocr_items(items: Iterable[Any], *, side: str | None = None) -> list[dict[str, Any]]:
    """Convenience wrapper that forces right-to-left ordering within lines."""

    return order_ocr_items(items, direction="rtl", side=side)


def ocr_lines(items: Iterable[Any], *, direction: str = "auto", side: str | None = None) -> list[str]:
    """Join ordered OCR words into normalized text lines."""

    ordered = order_ocr_items(items, direction=direction, side=side)
    lines: dict[int, list[str]] = {}
    unpositioned_line = max((item.get("line_index", -1) for item in ordered), default=-1) + 1
    for item in ordered:
        text = item.get("normalized_text")
        if not text:
            continue
        line_index = item.get("line_index", unpositioned_line)
        lines.setdefault(line_index, []).append(text)
        if "line_index" not in item:
            unpositioned_line += 1
    return [" ".join(lines[index]) for index in sorted(lines)]

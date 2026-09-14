"""Template- and label-based extraction of structured CNIC fields.

``parse_fields`` consumes OCR evidence grouped by document side and returns a
stable mapping for response serialization and validation.  It never fills a
field by changing ambiguous OCR characters; unreadable or absent fields remain
``None``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
import re
from typing import Any

from .normalization import bbox_bounds, normalize_text, order_ocr_items


FIELD_NAMES = (
    "name",
    "guardian_name",
    "gender",
    "country_of_stay",
    "cnic_number",
    "date_of_birth",
    "date_of_issue",
    "date_of_expiry",
)

TEMPLATE_FIELDS = {
    "generic": FIELD_NAMES,
    "smart": FIELD_NAMES,
    "smart_card": FIELD_NAMES,
    "nicop": FIELD_NAMES,
    "legacy_urdu": tuple(field for field in FIELD_NAMES if field != "country_of_stay"),
}

FIELD_ALIASES = {
    "name": (
        "name",
        "نام",
    ),
    "guardian_name": (
        "father name",
        "father's name",
        "guardian name",
        "husband name",
        "mother name",
        "والد کا نام",
        "والدہ کا نام",
        "شوہر کا نام",
        "سرپرست کا نام",
    ),
    "gender": (
        "gender",
        "sex",
        "جنس",
    ),
    "country_of_stay": (
        "country of stay",
        "country",
        "ملک قیام",
        "ملک",
    ),
    "cnic_number": (
        "identity number",
        "national identity number",
        "cnic number",
        "cnic",
        "شناختی کارڈ نمبر",
        "قومی شناختی نمبر",
        "شناختی نمبر",
    ),
    "date_of_birth": (
        "date of birth",
        "birth date",
        "dob",
        "تاریخ پیدائش",
    ),
    "date_of_issue": (
        "date of issue",
        "issue date",
        "date of issuance",
        "تاریخ اجراء",
        "تاریخ اجرا",
    ),
    "date_of_expiry": (
        "date of expiry",
        "expiry date",
        "expiration date",
        "date of expiration",
        "تاریخ تنسیخ",
        "تاریخ اختتام",
    ),
}

EXPIRY_LIFETIME = "lifetime"
EXPIRY_NO_EXPIRY = "no_expiry"

_LIFETIME_MARKERS = {
    "lifetime",
    "life time",
    "valid for life",
    "تا حیات",
    "تاحیات",
    "عمر بھر",
}
_NO_EXPIRY_MARKERS = {
    "no expiry",
    "no expiration",
    "no expiry date",
    "does not expire",
    "without expiry",
    "بلا میعاد",
}
_LABEL_DELIMITERS = " :：-–—|."
_DASH_TRANSLATION = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"})
_CANONICAL_CNIC = re.compile(r"^[0-9]{5}-[0-9]{7}-[0-9]$")
_CNIC_COMPONENTS = re.compile(r"^([0-9]{5})\s*-?\s*([0-9]{7})\s*-?\s*([0-9])$")
_DATE_PATTERNS = ("%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d")


def canonicalize_cnic(value: Any) -> str | None:
    """Normalize a 13-digit CNIC to ``#####-#######-#`` without OCR guesses."""

    text = normalize_text(value)
    if not text:
        return None
    text = text.translate(_DASH_TRANSLATION)
    match = _CNIC_COMPONENTS.fullmatch(text)
    if not match:
        return text
    return "-".join(match.groups())


def normalize_date(value: Any) -> str | None:
    """Normalize an unambiguous full date to ISO-8601; otherwise retain text."""

    text = normalize_text(value)
    if not text:
        return None
    for pattern in _DATE_PATTERNS:
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    return text


def normalize_expiry(value: Any) -> str | None:
    """Normalize a date or an explicitly supported non-expiring marker."""

    text = normalize_text(value)
    if not text:
        return None
    marker = text.casefold()
    if marker in {item.casefold() for item in _LIFETIME_MARKERS}:
        return EXPIRY_LIFETIME
    if marker in {item.casefold() for item in _NO_EXPIRY_MARKERS}:
        return EXPIRY_NO_EXPIRY
    return normalize_date(text)


def _normalize_gender(value: Any) -> str | None:
    text = normalize_text(value)
    if not text:
        return None
    marker = text.casefold().rstrip(".")
    if marker in {"m", "male", "مرد"}:
        return "M"
    if marker in {"f", "female", "عورت", "خاتون"}:
        return "F"
    if marker in {"x", "other", "غیر متعین"}:
        return "X"
    return text


def _normalize_field_value(field_name: str, value: Any) -> str | None:
    if value is None:
        return None
    if field_name == "cnic_number":
        return canonicalize_cnic(value)
    if field_name in {"date_of_birth", "date_of_issue"}:
        return normalize_date(value)
    if field_name == "date_of_expiry":
        return normalize_expiry(value)
    if field_name == "gender":
        return _normalize_gender(value)
    return normalize_text(value)


def _label_key(value: Any) -> str:
    text = normalize_text(value) or ""
    return text.casefold().strip(_LABEL_DELIMITERS)


_ALIASES_BY_LENGTH = sorted(
    (
        (_label_key(alias), field_name, alias)
        for field_name, aliases in FIELD_ALIASES.items()
        for alias in aliases
    ),
    key=lambda item: len(item[0]),
    reverse=True,
)


def canonical_field_name(value: Any) -> str | None:
    """Map a canonical/template label or printed label to a field name."""

    key = _label_key(value).replace(" ", "_")
    if key in FIELD_NAMES:
        return key
    plain_key = _label_key(value)
    for alias_key, field_name, _ in _ALIASES_BY_LENGTH:
        if plain_key == alias_key:
            return field_name
    return None


def _match_printed_label(text: Any) -> tuple[str, str, str] | None:
    """Return ``(field, alias, normalized_suffix)`` for a leading label."""

    normalized = normalize_text(text)
    if not normalized:
        return None
    folded = normalized.casefold()
    for alias_key, field_name, alias in _ALIASES_BY_LENGTH:
        if not folded.startswith(alias_key):
            continue
        suffix = normalized[len(alias_key) :]
        if suffix and suffix[0] not in _LABEL_DELIMITERS:
            continue
        return field_name, alias, suffix.strip(_LABEL_DELIMITERS)
    return None


def _raw_inline_value(raw_text: str | None, alias: str, normalized_suffix: str) -> str | None:
    if not raw_text:
        return normalized_suffix or None
    normalized_raw = normalize_text(raw_text) or ""
    normalized_alias = normalize_text(alias) or ""
    if normalized_raw.casefold().startswith(normalized_alias.casefold()):
        # The returned value is still derived solely from OCR characters.  The
        # untouched complete OCR line remains in evidence below.
        suffix = normalized_raw[len(normalized_alias) :].strip(_LABEL_DELIMITERS)
        return suffix or None
    return normalized_suffix or None


def _empty_field(*, supported: bool) -> dict[str, Any]:
    return {
        "raw_value": None,
        "normalized_value": None,
        "supported": supported,
        "evidence": [],
    }


def _evidence(
    item: Mapping[str, Any],
    raw_value: str | None,
    normalized_value: str | None,
    source: str,
    label_item: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "side": item.get("side"),
        "raw_text": item.get("raw_text"),
        "normalized_text": item.get("normalized_text"),
        "raw_value": raw_value,
        "normalized_value": normalized_value,
        "bbox": item.get("bbox"),
        "confidence": item.get("confidence"),
        "source": source,
    }
    if label_item is not None and label_item is not item:
        result["label"] = {
            "raw_text": label_item.get("raw_text"),
            "normalized_text": label_item.get("normalized_text"),
            "bbox": label_item.get("bbox"),
            "confidence": label_item.get("confidence"),
        }
    return result


def _assign(
    fields: dict[str, dict[str, Any]],
    field_name: str,
    item: Mapping[str, Any],
    raw_value: str | None,
    source: str,
    label_item: Mapping[str, Any] | None = None,
) -> None:
    normalized_value = _normalize_field_value(field_name, raw_value)
    if normalized_value == "":
        normalized_value = None
    evidence = _evidence(item, raw_value, normalized_value, source, label_item)
    fields[field_name]["evidence"].append(evidence)
    if fields[field_name]["normalized_value"] is None and normalized_value is not None:
        fields[field_name]["raw_value"] = raw_value
        fields[field_name]["normalized_value"] = normalized_value


def _looks_compatible(field_name: str, text: Any) -> bool:
    normalized = _normalize_field_value(field_name, text)
    if not normalized:
        return False
    if field_name == "cnic_number":
        return bool(_CANONICAL_CNIC.fullmatch(normalized))
    if field_name in {"date_of_birth", "date_of_issue"}:
        try:
            datetime.strptime(normalized, "%Y-%m-%d")
            return True
        except ValueError:
            return False
    if field_name == "date_of_expiry":
        if normalized in {EXPIRY_LIFETIME, EXPIRY_NO_EXPIRY}:
            return True
        try:
            datetime.strptime(normalized, "%Y-%m-%d")
            return True
        except ValueError:
            return False
    if field_name == "gender":
        return normalized in {"M", "F", "X"}
    return True


def _spatial_score(label_item: Mapping[str, Any], candidate: Mapping[str, Any]) -> float:
    label_bounds = bbox_bounds(label_item.get("bbox"))
    value_bounds = bbox_bounds(candidate.get("bbox"))
    if label_bounds is None or value_bounds is None:
        label_index = int(label_item.get("source_index", 0))
        value_index = int(candidate.get("source_index", 0))
        return abs(value_index - label_index) + (0 if value_index > label_index else 1000)

    lx = (label_bounds[0] + label_bounds[2]) / 2.0
    ly = (label_bounds[1] + label_bounds[3]) / 2.0
    vx = (value_bounds[0] + value_bounds[2]) / 2.0
    vy = (value_bounds[1] + value_bounds[3]) / 2.0
    label_height = max(1.0, label_bounds[3] - label_bounds[1])
    value_height = max(1.0, value_bounds[3] - value_bounds[1])
    vertical_distance = value_bounds[1] - label_bounds[3]
    same_line = abs(vy - ly) <= 0.7 * max(label_height, value_height)
    if same_line:
        return abs(vx - lx) + 0.5 * max(label_height, value_height)
    if vertical_distance < -0.5 * value_height:
        return 10000.0 + abs(vertical_distance) + abs(vx - lx)
    if vertical_distance > 8.0 * max(label_height, value_height):
        return 5000.0 + vertical_distance + abs(vx - lx)
    return max(0.0, vertical_distance) + 0.35 * abs(vx - lx)


def _choose_candidate(
    field_name: str,
    label_item: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    used: set[int],
) -> Mapping[str, Any] | None:
    compatible = [
        candidate
        for candidate in candidates
        if id(candidate) not in used and _looks_compatible(field_name, candidate.get("normalized_text"))
    ]
    if not compatible:
        return None
    candidate = min(compatible, key=lambda item: _spatial_score(label_item, item))
    return None if _spatial_score(label_item, candidate) >= 5000 else candidate


def parse_fields(
    ocr_by_side: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    template: str = "generic",
) -> dict[str, dict[str, Any]]:
    """Extract canonical fields from OCR evidence grouped by document side.

    Args:
        ocr_by_side: Mapping such as ``{"front": [...], "back": [...]}``.
            Each item should have ``side``, ``raw_text``, ``normalized_text``, a
            four-point ``bbox``, and ``confidence`` with ``value``,
            ``type='raw_ocr_score'``, and ``calibrated=false``.  ``field`` or
            ``field_name`` may be supplied by a template-specific detector.
        template: ``generic``, ``smart``, ``smart_card``, ``nicop``, or
            ``legacy_urdu``.

    Returns:
        A mapping containing every canonical field.  Each field has
        ``raw_value``, ``normalized_value``, ``supported``, and an evidence
        list.  Missing values are ``None``; characters are never guessed.
    """

    if not isinstance(ocr_by_side, Mapping):
        raise TypeError("ocr_by_side must map side names to OCR item lists.")
    template_key = str(template).casefold()
    if template_key not in TEMPLATE_FIELDS:
        raise ValueError(f"Unsupported CNIC template: {template}")
    supported_fields = set(TEMPLATE_FIELDS[template_key])
    fields = {name: _empty_field(supported=name in supported_fields) for name in FIELD_NAMES}

    ordered: list[dict[str, Any]] = []
    side_names = list(ocr_by_side)
    side_names.sort(key=lambda value: (str(value).casefold() != "front", str(value)))
    for side_name in side_names:
        items = ocr_by_side[side_name]
        if items is None:
            continue
        if isinstance(items, (str, bytes)) or not isinstance(items, Sequence):
            raise TypeError(f"OCR evidence for side {side_name!r} must be a sequence.")
        ordered.extend(order_ocr_items(items, direction="auto", side=str(side_name)))

    label_matches: dict[int, tuple[str, str, str]] = {}
    for item in ordered:
        matched = _match_printed_label(item.get("normalized_text"))
        if matched:
            label_matches[id(item)] = matched

    candidates = [item for item in ordered if id(item) not in label_matches and item.get("normalized_text")]
    used: set[int] = set()

    # A template/model-provided field label is the strongest association.
    for item in ordered:
        explicit = canonical_field_name(item.get("field")) or canonical_field_name(item.get("label"))
        if explicit is None or explicit not in supported_fields:
            continue
        raw_value = item.get("raw_text")
        _assign(fields, explicit, item, raw_value, "template_field")
        used.add(id(item))

    # Labels and values returned as one OCR line.
    for item in ordered:
        matched = label_matches.get(id(item))
        if matched is None:
            continue
        field_name, alias, normalized_suffix = matched
        if field_name not in supported_fields or not normalized_suffix:
            continue
        raw_value = _raw_inline_value(item.get("raw_text"), alias, normalized_suffix)
        _assign(fields, field_name, item, raw_value, "inline_label", item)
        used.add(id(item))

    # Standalone printed labels are associated geometrically with compatible
    # nearby values.  Format-specific fields require a valid-looking candidate;
    # the parser does not coerce letters into digits or infer missing dates.
    for item in ordered:
        matched = label_matches.get(id(item))
        if matched is None:
            continue
        field_name, _, normalized_suffix = matched
        if field_name not in supported_fields or normalized_suffix:
            continue
        candidate = _choose_candidate(field_name, item, candidates, used)
        if candidate is None:
            continue
        raw_value = candidate.get("raw_text")
        _assign(fields, field_name, candidate, raw_value, "spatial_label", item)
        used.add(id(candidate))

    # Full canonical CNIC values are sufficiently distinctive to retain as
    # evidence even when their printed labels were missed. Keep every side's
    # evidence so a back QR cannot mask a conflicting unlabeled front value.
    # Select a primary value only when the unmatched values do not conflict.
    if "cnic_number" in supported_fields:
        cnic_candidates = [
            item
            for item in candidates
            if id(item) not in used and _CANONICAL_CNIC.fullmatch(canonicalize_cnic(item.get("normalized_text")) or "")
        ]
        normalized_candidates: list[tuple[Mapping[str, Any], str]] = []
        for item in cnic_candidates:
            normalized_value = canonicalize_cnic(item.get("normalized_text"))
            if normalized_value is None:
                continue
            normalized_candidates.append((item, normalized_value))
            fields["cnic_number"]["evidence"].append(
                _evidence(
                    item,
                    item.get("raw_text"),
                    normalized_value,
                    "canonical_syntax",
                )
            )
        distinct_values = {value for _, value in normalized_candidates}
        if (
            fields["cnic_number"]["normalized_value"] is None
            and len(distinct_values) == 1
            and normalized_candidates
        ):
            selected, normalized_value = normalized_candidates[0]
            fields["cnic_number"]["raw_value"] = selected.get("raw_text")
            fields["cnic_number"]["normalized_value"] = normalized_value

    return fields

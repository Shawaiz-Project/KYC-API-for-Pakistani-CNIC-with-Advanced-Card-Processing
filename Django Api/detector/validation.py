"""Syntactic and date validation for parsed CNIC fields.

These checks do not query NADRA or any other issuing authority.  A syntactically
valid CNIC is not evidence that the number was issued, belongs to the bearer,
or is authentic.  Pakistan CNICs have no project-supported checksum; this
module intentionally invents none.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
import re
from typing import Any

from .normalization import normalize_text
from .parsing import EXPIRY_LIFETIME, EXPIRY_NO_EXPIRY, TEMPLATE_FIELDS, canonicalize_cnic


CHECK_STATUSES = frozenset({"pass", "fail", "uncertain", "not_run", "unavailable"})
_CANONICAL_CNIC = re.compile(r"^[0-9]{5}-[0-9]{7}-[0-9]$")
_ISO_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

REQUIRED_FIELDS_BY_TEMPLATE = {
    "generic": ("cnic_number", "date_of_birth", "date_of_issue", "date_of_expiry"),
    "smart": (
        "name",
        "guardian_name",
        "gender",
        "cnic_number",
        "date_of_birth",
        "date_of_issue",
        "date_of_expiry",
    ),
    "smart_card": (
        "name",
        "guardian_name",
        "gender",
        "cnic_number",
        "date_of_birth",
        "date_of_issue",
        "date_of_expiry",
    ),
    "nicop": TEMPLATE_FIELDS["nicop"],
    "legacy_urdu": ("cnic_number", "date_of_issue", "date_of_expiry"),
}


def _check(status: str, code: str, message: str, **details: Any) -> dict[str, Any]:
    if status not in CHECK_STATUSES:
        raise ValueError(f"Invalid check status: {status}")
    result: dict[str, Any] = {"status": status, "code": code, "message": message}
    if details:
        result["details"] = details
    return result


def _entry(fields: Mapping[str, Any], field_name: str) -> Any:
    return fields.get(field_name)


def _value(fields: Mapping[str, Any], field_name: str) -> Any:
    entry = _entry(fields, field_name)
    if isinstance(entry, Mapping):
        if "normalized_value" in entry:
            return entry.get("normalized_value")
        if "value" in entry:
            return entry.get("value")
    return entry


def _is_unavailable(entry: Any) -> bool:
    return isinstance(entry, Mapping) and (
        entry.get("availability") == "unavailable" or entry.get("status") == "unavailable"
    )


def _parse_iso(value: Any) -> date | None:
    text = normalize_text(value)
    if not text or not _ISO_DATE.fullmatch(text):
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def validate_cnic_syntax(value: Any) -> dict[str, Any]:
    """Validate only the canonical 5-7-1 decimal-digit CNIC syntax."""

    if value is None or normalize_text(value) == "":
        return _check("not_run", "cnic_missing", "CNIC syntax was not checked because no value was extracted.")
    normalized = canonicalize_cnic(value)
    if normalized and _CANONICAL_CNIC.fullmatch(normalized):
        return _check(
            "pass",
            "cnic_syntax_valid",
            "The CNIC has canonical 5-7-1 syntax. Issuance and authenticity were not checked.",
        )
    return _check("fail", "cnic_syntax_invalid", "The CNIC does not have canonical 5-7-1 syntax.")


def validate_required_fields(fields: Mapping[str, Any], required_fields: Iterable[str]) -> dict[str, Any]:
    required = tuple(dict.fromkeys(str(field) for field in required_fields))
    unavailable = [field for field in required if _is_unavailable(_entry(fields, field))]
    if unavailable:
        return _check(
            "unavailable",
            "required_fields_unavailable",
            "One or more required extraction results are unavailable.",
            fields=unavailable,
        )
    missing = [field for field in required if _value(fields, field) in {None, ""}]
    if missing:
        return _check(
            "fail",
            "required_fields_missing",
            "One or more required fields could not be read.",
            fields=missing,
        )
    return _check("pass", "required_fields_present", "All configured required fields were extracted.")


def validate_date_formats(fields: Mapping[str, Any]) -> dict[str, Any]:
    invalid: list[str] = []
    present = 0
    for field_name in ("date_of_birth", "date_of_issue", "date_of_expiry"):
        value = _value(fields, field_name)
        if value in {None, ""}:
            continue
        present += 1
        if field_name == "date_of_expiry" and value in {EXPIRY_LIFETIME, EXPIRY_NO_EXPIRY}:
            continue
        if _parse_iso(value) is None:
            invalid.append(field_name)
    if not present:
        return _check("not_run", "dates_missing", "Date format checks were not run because no dates were extracted.")
    if invalid:
        return _check(
            "fail",
            "date_format_invalid",
            "One or more extracted dates are not valid full calendar dates.",
            fields=invalid,
        )
    return _check("pass", "date_formats_valid", "All extracted dates use supported full-date formats.")


def validate_date_order(fields: Mapping[str, Any]) -> dict[str, Any]:
    birth = _parse_iso(_value(fields, "date_of_birth"))
    issue = _parse_iso(_value(fields, "date_of_issue"))
    expiry_value = _value(fields, "date_of_expiry")
    expiry = None if expiry_value in {EXPIRY_LIFETIME, EXPIRY_NO_EXPIRY} else _parse_iso(expiry_value)

    if birth is None or issue is None:
        return _check(
            "not_run",
            "date_order_prerequisite_missing",
            "Date ordering was not checked because birth or issue date is missing or unreadable.",
        )
    if birth > issue:
        return _check("fail", "birth_after_issue", "The birth date is later than the issue date.")
    if expiry_value in {EXPIRY_LIFETIME, EXPIRY_NO_EXPIRY}:
        return _check("pass", "date_order_valid_non_expiring", "Birth and issue dates are ordered; expiry is non-expiring.")
    if expiry is None:
        return _check(
            "not_run",
            "expiry_order_prerequisite_missing",
            "Expiry ordering was not checked because the expiry date is missing or unreadable.",
        )
    if issue > expiry:
        return _check("fail", "issue_after_expiry", "The issue date is later than the expiry date.")
    return _check("pass", "date_order_valid", "Birth, issue, and expiry dates are chronologically ordered.")


def validate_expiry(fields: Mapping[str, Any], *, today: date | None = None) -> dict[str, Any]:
    value = _value(fields, "date_of_expiry")
    if value in {None, ""}:
        return _check("not_run", "expiry_missing", "Expiry was not checked because no expiry value was extracted.")
    if value == EXPIRY_LIFETIME:
        return _check("pass", "lifetime_document", "The document explicitly uses a supported lifetime marker.")
    if value == EXPIRY_NO_EXPIRY:
        return _check("pass", "no_expiry_document", "The document explicitly uses a supported no-expiry marker.")
    expiry = _parse_iso(value)
    if expiry is None:
        return _check("uncertain", "expiry_unreadable", "Expiry could not be determined from the extracted value.")
    reference_date = today or date.today()
    if expiry < reference_date:
        return _check("fail", "document_expired", "The document expiry date is in the past.")
    return _check("pass", "document_not_expired", "The document is not expired on the reference date.")


def validate_side_consistency(fields: Mapping[str, Any]) -> dict[str, Any]:
    entry = _entry(fields, "cnic_number")
    if not isinstance(entry, Mapping):
        return _check("not_run", "side_consistency_not_run", "Only one structured CNIC value is available.")
    evidence = entry.get("evidence")
    if not isinstance(evidence, list):
        return _check("not_run", "side_consistency_not_run", "Only one structured CNIC value is available.")
    by_side: dict[str, set[str]] = {}
    for item in evidence:
        if not isinstance(item, Mapping):
            continue
        side = item.get("side")
        value = canonicalize_cnic(item.get("normalized_value"))
        if side and value and _CANONICAL_CNIC.fullmatch(value):
            by_side.setdefault(str(side), set()).add(value)
    if len(by_side) < 2:
        return _check("not_run", "side_consistency_not_run", "CNIC evidence was not available from two sides.")
    values = set().union(*by_side.values())
    if len(values) == 1 and all(len(side_values) == 1 for side_values in by_side.values()):
        return _check("pass", "cnic_sides_match", "Canonical CNIC evidence agrees across document sides.")
    return _check("fail", "cnic_sides_mismatch", "Canonical CNIC evidence conflicts across document sides.")


def _overall_status(checks: Mapping[str, Mapping[str, Any]]) -> str:
    statuses = {check.get("status") for check in checks.values()}
    if "fail" in statuses:
        return "fail"
    if "unavailable" in statuses:
        return "unavailable"
    if "uncertain" in statuses:
        return "uncertain"
    if "pass" in statuses:
        return "pass"
    return "not_run"


def validate_fields(
    normalized_fields: Mapping[str, Any],
    *,
    template: str = "generic",
    required_fields: Iterable[str] | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Run local structured-field validation and return aggregate checks.

    This entry point accepts either the mapping returned by ``parse_fields`` or
    a simple mapping of canonical field names to normalized strings.
    """

    if not isinstance(normalized_fields, Mapping):
        raise TypeError("normalized_fields must be a mapping.")
    template_key = str(template).casefold()
    if template_key not in REQUIRED_FIELDS_BY_TEMPLATE:
        raise ValueError(f"Unsupported CNIC template: {template}")
    required = required_fields if required_fields is not None else REQUIRED_FIELDS_BY_TEMPLATE[template_key]
    checks = {
        "required_fields": validate_required_fields(normalized_fields, required),
        "cnic_syntax": validate_cnic_syntax(_value(normalized_fields, "cnic_number")),
        "date_formats": validate_date_formats(normalized_fields),
        "date_order": validate_date_order(normalized_fields),
        "expiry": validate_expiry(normalized_fields, today=today),
        "side_consistency": validate_side_consistency(normalized_fields),
        "issuance": _check(
            "not_run",
            "issuance_not_checked",
            "Issuance and bearer identity require an authoritative external verification source.",
        ),
    }
    return {"overall_status": _overall_status(checks), "checks": checks}

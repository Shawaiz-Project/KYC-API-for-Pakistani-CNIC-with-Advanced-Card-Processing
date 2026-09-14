from __future__ import annotations

from datetime import datetime
from typing import Any


def separate_fields(parsed_fields: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    extracted: dict[str, Any] = {}
    evidence: dict[str, Any] = {}
    for name, entry in parsed_fields.items():
        extracted[name] = {
            "raw_value": entry.get("raw_value"),
            "normalized_value": entry.get("normalized_value"),
            "supported": bool(entry.get("supported", True)),
        }
        if entry.get("availability") == "unavailable":
            extracted[name]["availability"] = "unavailable"
        evidence[name] = list(entry.get("evidence") or [])
    return extracted, evidence


def legacy_response(result: dict[str, Any]) -> dict[str, Any]:
    """Map the v1 structured result to the historical six-key contract."""

    fields = result.get("extracted_fields", {})

    def value(field: str):
        entry = fields.get(field) or {}
        raw = entry.get("normalized_value")
        if raw is None:
            raw = entry.get("raw_value")
        return raw

    def legacy_text(field: str):
        raw = value(field)
        return None if raw is None else str(raw).replace(".", "")

    def legacy_date(field: str):
        raw = value(field)
        if raw is None:
            return None
        try:
            return datetime.strptime(str(raw), "%Y-%m-%d").strftime("%d%m%y")
        except ValueError:
            return str(raw).replace(".", "")

    cnic = legacy_text("cnic_number")
    if cnic:
        cnic = cnic.replace("-", "")
    return {
        "Name": legacy_text("name"),
        "Gaurdian Name": legacy_text("guardian_name"),
        "Id Card Number": cnic,
        "Data Of Birth": legacy_date("date_of_birth"),
        "Data Of Issue": legacy_date("date_of_issue"),
        "Data Of Expiry": legacy_date("date_of_expiry"),
    }


def has_legacy_side_mismatch(result: dict[str, Any]) -> bool:
    check = result.get("validation", {}).get("checks", {}).get("side_consistency", {})
    return check.get("code") == "cnic_sides_mismatch" and check.get("status") == "fail"

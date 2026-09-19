from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings


@dataclass(frozen=True)
class DocumentType:
    key: str
    status: str
    fields: tuple[str, ...]
    expected_regions: tuple[str, ...]
    validator: str


def registry() -> dict[str, DocumentType]:
    return {
        "pakistani_cnic": DocumentType("pakistani_cnic", "supported", ("name", "cnic_number", "date_of_birth", "date_of_issue", "date_of_expiry"), ("portrait", "logo", "chip", "signature", "text"), "cnic_syntax_and_dates"),
        "passport_td3": DocumentType("passport_td3", "pilot" if settings.KYC_FEATURE_PASSPORT_MRZ else "disabled", ("document_number", "name", "nationality", "date_of_birth", "date_of_expiry"), ("portrait", "mrz"), "icao_9303_mrz_check_digits"),
        "pakistan_punjab_driving_license_v1": DocumentType("pakistan_punjab_driving_license_v1", "pilot" if settings.KYC_FEATURE_PUNJAB_DRIVING_LICENSE else "disabled", ("name", "license_number", "date_of_birth", "date_of_expiry"), ("portrait", "logo", "text"), "pilot_layout_only"),
    }


def mrz_check_digit(value: str) -> str:
    values = {str(index): index for index in range(10)}
    values.update({chr(ord("A") + index): 10 + index for index in range(26)})
    values["<"] = 0
    weights = (7, 3, 1)
    return str(sum(values.get(char, 0) * weights[index % 3] for index, char in enumerate(value.upper())) % 10)


def parse_td3_mrz(line1: str, line2: str) -> dict:
    """Parse and validate an ICAO TD3 MRZ without claiming authenticity."""

    first, second = line1.strip().upper(), line2.strip().upper()
    if len(first) != 44 or len(second) != 44 or not first.startswith("P<"):
        return {"status": "fail", "reason_codes": ["invalid_td3_shape"], "fields": {}}
    fields = {
        "document_code": first[0:2].replace("<", ""),
        "issuing_state": first[2:5].replace("<", ""),
        "name": " ".join(first[5:44].replace("<<", ", ").replace("<", " ").split()),
        "document_number": second[0:9].replace("<", ""),
        "nationality": second[10:13].replace("<", ""),
        "date_of_birth_mrz": second[13:19],
        "sex": second[20].replace("<", "X"),
        "date_of_expiry_mrz": second[21:27],
        "personal_number": second[28:42].replace("<", ""),
    }
    checks = {
        "document_number": mrz_check_digit(second[0:9]) == second[9],
        "date_of_birth": mrz_check_digit(second[13:19]) == second[19],
        "date_of_expiry": mrz_check_digit(second[21:27]) == second[27],
        "personal_number": second[42] == "<" or mrz_check_digit(second[28:42]) == second[42],
        "composite": mrz_check_digit(second[0:10] + second[13:20] + second[21:43]) == second[43],
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "status": "pass" if not failed else "fail",
        "reason_codes": ["mrz_internal_checks_passed"] if not failed else [f"mrz_check_digit_failed:{name}" for name in failed],
        "fields": fields,
        "checks": checks,
        "authenticity_claimed": False,
    }

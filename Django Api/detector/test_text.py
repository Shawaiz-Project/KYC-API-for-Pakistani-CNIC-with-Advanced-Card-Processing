from datetime import date
import unittest

from detector.normalization import normalize_text, order_urdu_ocr_items
from detector.parsing import (
    EXPIRY_LIFETIME,
    EXPIRY_NO_EXPIRY,
    canonicalize_cnic,
    parse_fields,
)
from detector.validation import CHECK_STATUSES, validate_cnic_syntax, validate_fields


def box(x1, y1, x2, y2):
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def item(text, x1, y1, x2, y2, *, confidence=0.8, side="front", **extra):
    value = {
        "side": side,
        "raw_text": text,
        "normalized_text": normalize_text(text),
        "bbox": box(x1, y1, x2, y2),
        "confidence": {"value": confidence, "type": "raw_ocr_score", "calibrated": False},
    }
    value.update(extra)
    return value


class NormalizationTests(unittest.TestCase):
    def test_nfkc_digits_whitespace_and_bidi_controls(self):
        self.assertEqual(normalize_text("\u202b۱۲۳\u00a0٤٥\u202c"), "123 45")
        self.assertEqual(normalize_text("ＡＢＣ"), "ABC")

    def test_urdu_words_are_right_to_left_and_lines_top_to_bottom(self):
        source = [
            item("احمد", 0, 30, 40, 40, confidence=0.51),
            item("علی", 0, 10, 30, 20, confidence=0.52),
            item("والد", 80, 30, 120, 40, confidence=0.53),
            item("نام", 80, 10, 120, 20, confidence=0.54),
        ]
        ordered = order_urdu_ocr_items(source)
        self.assertEqual([entry["raw_text"] for entry in ordered], ["نام", "علی", "والد", "احمد"])
        self.assertEqual(ordered[0]["confidence"], {"value": 0.54, "type": "raw_ocr_score", "calibrated": False})
        self.assertEqual(ordered[0]["bbox"], box(80, 10, 120, 20))


class ParsingTests(unittest.TestCase):
    def test_inline_labels_extract_all_supported_fields_and_preserve_evidence(self):
        front = [
            item("Name: علی رضا", 0, 0, 120, 10, confidence=0.91),
            item("Father Name: احمد رضا", 0, 15, 150, 25, confidence=0.82),
            item("Gender: Male", 0, 30, 90, 40),
            item("Country of Stay: Pakistan", 0, 45, 170, 55),
            item("Identity Number: ۳۵۲۰۲-۱۲۳۴۵۶۷-۱", 0, 60, 220, 70, confidence=0.73),
            item("Date of Birth: ۰۱.۰۲.۱۹۹۰", 0, 75, 170, 85),
            item("Date of Issue: ۰۱/۰۲/۲۰۱۰", 0, 90, 170, 100),
            item("Date of Expiry: LIFE TIME", 0, 105, 180, 115),
        ]
        fields = parse_fields({"front": front}, template="nicop")

        self.assertEqual(fields["name"]["normalized_value"], "علی رضا")
        self.assertEqual(fields["guardian_name"]["normalized_value"], "احمد رضا")
        self.assertEqual(fields["gender"]["normalized_value"], "M")
        self.assertEqual(fields["country_of_stay"]["normalized_value"], "Pakistan")
        self.assertEqual(fields["cnic_number"]["normalized_value"], "35202-1234567-1")
        self.assertEqual(fields["date_of_birth"]["normalized_value"], "1990-02-01")
        self.assertEqual(fields["date_of_issue"]["normalized_value"], "2010-02-01")
        self.assertEqual(fields["date_of_expiry"]["normalized_value"], EXPIRY_LIFETIME)

        evidence = fields["cnic_number"]["evidence"][0]
        self.assertEqual(evidence["raw_text"], "Identity Number: ۳۵۲۰۲-۱۲۳۴۵۶۷-۱")
        self.assertEqual(evidence["bbox"], box(0, 60, 220, 70))
        self.assertEqual(evidence["confidence"]["value"], 0.73)
        self.assertFalse(evidence["confidence"]["calibrated"])

    def test_template_field_items_are_supported(self):
        fields = parse_fields(
            {
                "front": [
                    item("فاطمہ", 10, 10, 80, 20, field="name"),
                    item("۴۲۱۰۱۱۲۳۴۵۶۷۸", 10, 30, 120, 40, field_name="cnic_number"),
                ]
            }
        )
        self.assertEqual(fields["name"]["normalized_value"], "فاطمہ")
        self.assertEqual(fields["cnic_number"]["normalized_value"], "42101-1234567-8")
        self.assertEqual(fields["name"]["evidence"][0]["source"], "template_field")

    def test_unreadable_field_stays_null(self):
        fields = parse_fields({"front": [item("Name", 0, 0, 50, 10)]})
        self.assertIsNone(fields["name"]["raw_value"])
        self.assertIsNone(fields["name"]["normalized_value"])
        self.assertEqual(fields["name"]["evidence"], [])

    def test_cnic_normalization_does_not_substitute_letters(self):
        self.assertEqual(canonicalize_cnic("۳۵۲۰۲۱۲۳۴۵۶۷۱"), "35202-1234567-1")
        self.assertEqual(canonicalize_cnic("35O02-1234567-1"), "35O02-1234567-1")

    def test_no_expiry_marker_is_explicit(self):
        fields = parse_fields({"front": [item("Date of Expiry: No Expiry", 0, 0, 150, 10)]})
        self.assertEqual(fields["date_of_expiry"]["normalized_value"], EXPIRY_NO_EXPIRY)


class ValidationTests(unittest.TestCase):
    def _valid_fields(self, expiry="2035-02-01"):
        return {
            "name": "Ali",
            "guardian_name": "Ahmed",
            "gender": "M",
            "country_of_stay": "Pakistan",
            "cnic_number": "35202-1234567-1",
            "date_of_birth": "1990-02-01",
            "date_of_issue": "2020-02-01",
            "date_of_expiry": expiry,
        }

    def test_cnic_check_is_syntax_only(self):
        valid = validate_cnic_syntax("۳۵۲۰۲-۱۲۳۴۵۶۷-۱")
        self.assertEqual(valid["status"], "pass")
        self.assertIn("Issuance", valid["message"])
        self.assertEqual(validate_cnic_syntax("35202-123456-1")["status"], "fail")

    def test_valid_dates_and_future_expiry_pass(self):
        result = validate_fields(self._valid_fields(), template="nicop", today=date(2030, 1, 1))
        self.assertEqual(result["overall_status"], "pass")
        self.assertEqual(result["checks"]["date_order"]["status"], "pass")
        self.assertEqual(result["checks"]["expiry"]["status"], "pass")
        self.assertEqual(result["checks"]["issuance"]["status"], "not_run")

    def test_lifetime_and_no_expiry_are_supported(self):
        lifetime = validate_fields(self._valid_fields(EXPIRY_LIFETIME), today=date(2099, 1, 1))
        no_expiry = validate_fields(self._valid_fields(EXPIRY_NO_EXPIRY), today=date(2099, 1, 1))
        self.assertEqual(lifetime["checks"]["expiry"]["code"], "lifetime_document")
        self.assertEqual(no_expiry["checks"]["expiry"]["code"], "no_expiry_document")
        self.assertEqual(lifetime["overall_status"], "pass")
        self.assertEqual(no_expiry["overall_status"], "pass")

    def test_expired_and_out_of_order_dates_fail(self):
        expired = validate_fields(self._valid_fields("2025-01-01"), today=date(2030, 1, 1))
        self.assertEqual(expired["checks"]["expiry"]["status"], "fail")
        fields = self._valid_fields()
        fields["date_of_birth"] = "2022-01-01"
        result = validate_fields(fields, today=date(2030, 1, 1))
        self.assertEqual(result["checks"]["date_order"]["status"], "fail")
        self.assertEqual(result["overall_status"], "fail")

    def test_missing_required_field_fails_without_inventing_value(self):
        fields = self._valid_fields()
        fields["cnic_number"] = None
        result = validate_fields(fields, today=date(2030, 1, 1))
        self.assertEqual(result["checks"]["required_fields"]["status"], "fail")
        self.assertEqual(result["checks"]["cnic_syntax"]["status"], "not_run")

    def test_conflicting_cross_side_evidence_fails(self):
        fields = self._valid_fields()
        fields["cnic_number"] = {
            "normalized_value": "35202-1234567-1",
            "evidence": [
                {"side": "front", "normalized_value": "35202-1234567-1"},
                {"side": "back", "normalized_value": "35202-7654321-1"},
            ],
        }
        result = validate_fields(fields, today=date(2030, 1, 1))
        self.assertEqual(result["checks"]["side_consistency"]["status"], "fail")

    def test_every_check_uses_contract_status(self):
        result = validate_fields({}, required_fields=())
        for check in result["checks"].values():
            self.assertIn(check["status"], CHECK_STATUSES)
        self.assertIn(result["overall_status"], CHECK_STATUSES)


if __name__ == "__main__":
    unittest.main()

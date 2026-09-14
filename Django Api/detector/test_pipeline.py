from __future__ import annotations

import json
from unittest.mock import MagicMock, Mock, call, patch

import cv2
import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase
from rest_framework import status

from detector.errors import KYCError
from detector.model_registry import ModelUnavailableError
from detector.pipeline import process_pair
from detector.preprocessing import CardDetection, PreprocessingResult, QualityFinding
from detector.serialization import has_legacy_side_mismatch, legacy_response
from detector.side_detection import classify_document_side


def _polygon(x1: float, y1: float, x2: float, y2: float) -> list[list[float]]:
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _ocr_item(text: str, y: float, *, side: str = "front", score: float = 0.81) -> dict:
    return {
        "side": side,
        "raw_text": text,
        "normalized_text": text,
        "bbox": _polygon(10, y, 310, y + 18),
        "confidence": {
            "value": score,
            "type": "raw_ocr_score",
            "calibrated": False,
        },
    }


def _uploaded_jpeg(name: str, value: int) -> tuple[SimpleUploadedFile, bytes]:
    # The checkerboard keeps this synthetic fixture visibly non-documentary and
    # gives the encoder non-uniform pixels without using a repository fixture.
    image = np.full((72, 112, 3), value, dtype=np.uint8)
    image[::8, :, :] = min(value + 35, 255)
    image[:, ::8, :] = max(value - 25, 0)
    encoded_ok, encoded = cv2.imencode(".jpg", image)
    if not encoded_ok:  # pragma: no cover - an OpenCV installation failure
        raise RuntimeError("Could not create an in-memory JPEG fixture")
    content = encoded.tobytes()
    return SimpleUploadedFile(name, content, content_type="image/jpeg"), content


def _side_result(detected_side: str, *, qr_cnic: str | None = None) -> dict:
    return {
        "detected_side": detected_side,
        "status": "pass" if detected_side in {"front", "back"} else "uncertain",
        "confidence": {
            "value": 0.9 if detected_side in {"front", "back"} else 0.0,
            "type": "heuristic_score",
            "calibrated": False,
        },
        "signals": {
            "face_count": int(detected_side == "front"),
            "qr_count": int(qr_cnic is not None),
            "front_keyword_count": 0,
            "back_keyword_count": 0,
        },
        "qr_cnic": qr_cnic,
    }


def _processed(side: str, value: int) -> PreprocessingResult:
    corrected = np.full((400, 640, 3), value, dtype=np.uint8)
    corrected[::20, :, :] = min(value + 40, 255)
    detection = CardDetection(
        status="single_card",
        count=1,
        source="contour",
        corners=((0.0, 0.0), (639.0, 0.0), (639.0, 399.0), (0.0, 399.0)),
        area_ratio=0.72,
        complete=True,
        model_detection_count=0,
    )
    findings = (
        QualityFinding("blur", "pass", 120.0, {"minimum": 80.0}, "Synthetic image passed blur gate."),
        QualityFinding("exposure", "pass", value, {"minimum": 45, "maximum": 225}, "Exposure passed."),
        QualityFinding("glare", "pass", 0.0, {"maximum": 0.08}, "Glare passed."),
        QualityFinding(
            "minimum_resolution",
            "pass",
            {"width": 640, "height": 400},
            {"minimum_width": 640, "minimum_height": 400},
            "Resolution passed.",
        ),
    )
    return PreprocessingResult(
        corrected_image=corrected,
        detection=detection,
        quality_findings=findings,
        recapture_reasons=(),
        orientation_degrees=0,
        card_rotation_degrees=0,
        side_signal=side,
        expected_side=side,
    )


def _valid_front_ocr(*, expiry: str = "01.01.2099") -> list[dict]:
    return [
        _ocr_item("Identity Number: 00000-0000000-0", 10, score=0.77),
        _ocr_item("Date of Birth: 01.01.2000", 35, score=0.78),
        _ocr_item("Date of Issue: 01.01.2020", 60, score=0.79),
        _ocr_item(f"Date of Expiry: {expiry}", 85, score=0.80),
    ]


class PipelineHarness(SimpleTestCase):
    def _run_pipeline(
        self,
        *,
        front_ocr: list[dict] | None = None,
        back_ocr: list[dict] | None = None,
        front_side: dict | None = None,
        back_side: dict | None = None,
        preprocess_side_effect=None,
        registry=None,
    ):
        front_upload, front_bytes = _uploaded_jpeg("front.jpg", 95)
        back_upload, back_bytes = _uploaded_jpeg("back.jpg", 145)

        if registry is None:
            registry = Mock()
            registry.get_card_detector.return_value = None
            registry.versions.return_value = {
                "card_boundary": {
                    "name": "opencv-contour-baseline",
                    "version": "test",
                    "kind": "deterministic_heuristic",
                },
                "ocr": {
                    "name": "EasyOCR",
                    "version": "test",
                    "confidence": "raw_model_score_not_calibrated_probability",
                },
            }

        storage = MagicMock(name="request_storage")
        storage.__enter__.return_value = storage
        storage.__exit__.return_value = None

        ocr_by_side = {
            "front": list(front_ocr if front_ocr is not None else _valid_front_ocr()),
            "back": list(back_ocr or []),
        }
        side_by_name = {
            "front": front_side if front_side is not None else _side_result("front"),
            "back": back_side if back_side is not None else _side_result("back", qr_cnic="00000-0000000-0"),
        }

        def recognize(_image, side):
            # Return fresh containers because process_pair appends QR evidence.
            return [dict(item) for item in ocr_by_side[side]]

        side_call = iter((side_by_name["front"], side_by_name["back"]))

        def preprocess(_validated, side, _detector):
            if preprocess_side_effect is not None:
                if callable(preprocess_side_effect):
                    return preprocess_side_effect(_validated, side, _detector)
                raise preprocess_side_effect
            return (_processed(side, 105 if side == "front" else 155), [])

        self.last_storage = storage
        self.last_original_bytes = {"front": front_bytes, "back": back_bytes}
        with patch("detector.pipeline.get_model_registry", return_value=registry), patch(
            "detector.pipeline.RequestStorage.create", return_value=storage
        ), patch("detector.pipeline._preprocess", side_effect=preprocess), patch(
            "detector.pipeline.recognize_text", side_effect=recognize
        ), patch("detector.pipeline.classify_document_side", side_effect=lambda *_: next(side_call)):
            result = process_pair(front_upload, back_upload, "request-test-001")
        return result


class FullPipelineContractTests(PipelineHarness):
    def test_full_response_contract_retains_raw_uncalibrated_evidence_and_nulls(self):
        result = self._run_pipeline()

        self.assertEqual(
            set(result),
            {
                "request_id",
                "api_version",
                "processing",
                "verification",
                "document",
                "quality",
                "extracted_fields",
                "field_evidence",
                "ocr",
                "validation",
                "model_versions",
            },
        )
        self.assertEqual(result["request_id"], "request-test-001")
        self.assertEqual(result["api_version"], "v1")
        self.assertEqual(result["processing"]["success"], True)
        self.assertEqual(result["processing"]["status"], "completed")
        self.assertIsInstance(result["processing"]["duration_ms"], float)
        self.assertEqual(result["document"]["type"], "pakistani_cnic")
        self.assertEqual(result["document"]["detected_sides"]["front_upload"]["detected_side"], "front")
        self.assertEqual(result["document"]["detected_sides"]["back_upload"]["detected_side"], "back")
        self.assertNotIn("qr_cnic", result["document"]["detected_sides"]["back_upload"])
        self.assertEqual(result["quality"]["overall_status"], "pass")
        self.assertEqual(len(result["quality"]["front"]), 4)

        # Optional text fields stay null; the pipeline never invents values.
        self.assertEqual(
            result["extracted_fields"]["name"],
            {"raw_value": None, "normalized_value": None, "supported": True},
        )
        self.assertIsNone(result["extracted_fields"]["guardian_name"]["normalized_value"])
        self.assertIsNone(result["extracted_fields"]["gender"]["normalized_value"])
        self.assertIsNone(result["extracted_fields"]["country_of_stay"]["normalized_value"])

        raw = result["ocr"]["raw_detections"]["front"][0]
        self.assertEqual(raw["raw_text"], "Identity Number: 00000-0000000-0")
        self.assertEqual(raw["bbox"], _polygon(10, 10, 310, 28))
        self.assertEqual(raw["confidence"]["value"], 0.77)
        self.assertEqual(raw["confidence"]["type"], "raw_ocr_score")
        self.assertIs(raw["confidence"]["calibrated"], False)

        cnic_evidence = result["field_evidence"]["cnic_number"]
        self.assertEqual({entry["side"] for entry in cnic_evidence}, {"front", "back"})
        front_evidence = next(entry for entry in cnic_evidence if entry["side"] == "front")
        self.assertEqual(front_evidence["raw_text"], "Identity Number: 00000-0000000-0")
        self.assertIs(front_evidence["confidence"]["calibrated"], False)
        self.assertEqual(result["validation"]["checks"]["side_consistency"]["status"], "pass")
        self.assertFalse(result["verification"]["authoritative_issuance_checked"])
        self.assertIn("not proof", result["verification"]["message"])

        # The complete result must be ready for a JSON response without custom
        # encoders, NumPy objects, image bytes, or storage paths.
        json.dumps(result)

    def test_processing_success_is_separate_from_fail_and_uncertain_verification(self):
        failed = self._run_pipeline(front_ocr=_valid_front_ocr(expiry="01.01.2020"))
        self.assertTrue(failed["processing"]["success"])
        self.assertEqual(failed["processing"]["status"], "completed")
        self.assertEqual(failed["validation"]["overall_status"], "fail")
        self.assertEqual(failed["verification"]["decision"], "fail")

        uncertain = self._run_pipeline(
            front_side=_side_result("unknown"),
            back_side=_side_result("unknown", qr_cnic="00000-0000000-0"),
        )
        self.assertTrue(uncertain["processing"]["success"])
        self.assertEqual(uncertain["validation"]["overall_status"], "uncertain")
        self.assertEqual(uncertain["verification"]["decision"], "uncertain")

    def test_original_and_processing_copies_use_separate_storage_calls(self):
        self._run_pipeline()
        storage = self.last_storage

        storage.save_original.assert_has_calls(
            [
                call("front", self.last_original_bytes["front"]),
                call("back", self.last_original_bytes["back"]),
            ]
        )
        self.assertEqual(storage.save_original.call_count, 2)
        self.assertEqual(storage.save_processing_copy.call_count, 2)
        processing_calls = storage.save_processing_copy.call_args_list
        self.assertEqual([entry.args[0] for entry in processing_calls], ["front", "back"])
        self.assertTrue(all(entry.args[1].startswith(b"\x89PNG\r\n\x1a\n") for entry in processing_calls))
        self.assertNotEqual(processing_calls[0].args[1], self.last_original_bytes["front"])
        self.assertNotEqual(processing_calls[1].args[1], self.last_original_bytes["back"])


class PipelineErrorTests(PipelineHarness):
    def test_wrong_side_is_a_specific_recapture_error(self):
        with self.assertRaises(KYCError) as raised:
            self._run_pipeline(front_side=_side_result("back"))

        self.assertEqual(raised.exception.code, "wrong_document_side")
        self.assertEqual(raised.exception.http_status, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertEqual(raised.exception.details["expected_side"], "front")
        self.assertEqual(raised.exception.details["detected_side"], "back")
        self.assertEqual(raised.exception.details["recapture_reasons"], ["wrong_side"])

    def test_quality_error_is_propagated_without_rewriting_details(self):
        quality_error = KYCError(
            "image_quality_insufficient",
            "Synthetic image failed a quality gate.",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"side": "front", "recapture_reasons": ["image_blurry"]},
        )
        with self.assertRaises(KYCError) as raised:
            self._run_pipeline(preprocess_side_effect=quality_error)

        self.assertIs(raised.exception, quality_error)
        self.assertEqual(raised.exception.details, {"side": "front", "recapture_reasons": ["image_blurry"]})

    def test_required_model_error_is_propagated_before_storage(self):
        registry = Mock()
        model_error = ModelUnavailableError("card detector", "sha256_mismatch")
        registry.get_card_detector.side_effect = model_error

        with self.assertRaises(ModelUnavailableError) as raised:
            self._run_pipeline(registry=registry)

        self.assertIs(raised.exception, model_error)
        self.assertEqual(raised.exception.http_status, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.last_storage.__enter__.assert_not_called()
        self.last_storage.save_original.assert_not_called()


class QREvidenceTests(SimpleTestCase):
    def test_qr_exposes_only_canonical_cnic_evidence_not_full_payload(self):
        image = np.zeros((80, 120, 3), dtype=np.uint8)
        payload = "private-prefix|00000-0000000-0|private-suffix"
        face_detector = Mock()
        face_detector.detectMultiScale.return_value = ()

        with patch("detector.side_detection._FACE_CASCADE", face_detector), patch(
            "detector.side_detection._decode_qr_payloads", return_value=[payload]
        ):
            result = classify_document_side(image, [])

        self.assertEqual(result["detected_side"], "back")
        self.assertEqual(result["signals"]["qr_count"], 1)
        self.assertEqual(result["qr_cnic"], "00000-0000000-0")
        serialized = json.dumps(result)
        self.assertNotIn("private-prefix", serialized)
        self.assertNotIn("private-suffix", serialized)
        self.assertNotIn(payload, serialized)
        self.assertIs(result["confidence"]["calibrated"], False)


class LegacySerializationTests(SimpleTestCase):
    def test_exact_historical_keys_values_and_date_mapping(self):
        result = {
            "extracted_fields": {
                "name": {"raw_value": "Raw.Name", "normalized_value": "Test.Person"},
                "guardian_name": {"raw_value": "Raw.Guardian", "normalized_value": "Test.Guardian"},
                "cnic_number": {"raw_value": None, "normalized_value": "00000-0000000-0"},
                "date_of_birth": {"raw_value": None, "normalized_value": "2000-01-02"},
                "date_of_issue": {"raw_value": None, "normalized_value": "2020-03-04"},
                "date_of_expiry": {"raw_value": None, "normalized_value": "2099-12-31"},
            }
        }

        self.assertEqual(
            legacy_response(result),
            {
                "Name": "TestPerson",
                "Gaurdian Name": "TestGuardian",
                "Id Card Number": "0000000000000",
                "Data Of Birth": "020100",
                "Data Of Issue": "040320",
                "Data Of Expiry": "311299",
            },
        )

    def test_legacy_mismatch_detection_requires_exact_failed_check(self):
        mismatch = {
            "validation": {
                "checks": {
                    "side_consistency": {"status": "fail", "code": "cnic_sides_mismatch"}
                }
            }
        }
        uncertain = {
            "validation": {
                "checks": {
                    "side_consistency": {"status": "uncertain", "code": "cnic_sides_mismatch"}
                }
            }
        }
        unrelated_failure = {
            "validation": {
                "checks": {
                    "side_consistency": {"status": "fail", "code": "side_unreadable"}
                }
            }
        }

        self.assertTrue(has_legacy_side_mismatch(mismatch))
        self.assertFalse(has_legacy_side_mismatch(uncertain))
        self.assertFalse(has_legacy_side_mismatch(unrelated_failure))
        self.assertFalse(has_legacy_side_mismatch({}))

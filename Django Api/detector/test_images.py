from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

import cv2
import numpy as np
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from PIL import Image, features

from .errors import KYCError
from .preprocessing import assess_quality, preprocess_document
from .uploads import validate_upload


def _cv_upload(image: np.ndarray, *, suffix: str = ".png", name: str = "capture.png"):
    encoded, buffer = cv2.imencode(suffix, image)
    if not encoded:
        raise AssertionError("Synthetic test image could not be encoded")
    return SimpleUploadedFile(name, buffer.tobytes(), content_type="application/octet-stream")


def _pillow_upload(
    size: tuple[int, int],
    image_format: str,
    *,
    name: str,
    exif_orientation: int | None = None,
) -> SimpleUploadedFile:
    image = Image.new("RGB", size, (40, 120, 180))
    output = BytesIO()
    save_options = {}
    if exif_orientation is not None:
        exif = Image.Exif()
        exif[274] = exif_orientation
        save_options["exif"] = exif
    image.save(output, format=image_format, **save_options)
    return SimpleUploadedFile(name, output.getvalue(), content_type="application/octet-stream")


def _draw_card(canvas: np.ndarray, points: np.ndarray, *, glare: bool = False) -> None:
    cv2.fillConvexPoly(canvas, points, (135, 145, 150), lineType=cv2.LINE_AA)
    cv2.polylines(canvas, [points], True, (220, 225, 230), 7, cv2.LINE_AA)
    x, y, width, height = cv2.boundingRect(points)
    cv2.putText(
        canvas,
        "PAKISTAN ID CARD",
        (x + max(20, width // 12), y + max(55, height // 4)),
        cv2.FONT_HERSHEY_SIMPLEX,
        max(0.7, min(width, height) / 550),
        (20, 30, 40),
        3,
        cv2.LINE_AA,
    )
    for offset in (2, 3, 4):
        line_y = y + (height * offset) // 6
        cv2.line(
            canvas,
            (x + width // 8, line_y),
            (x + (width * 7) // 8, line_y),
            (35, 45, 55),
            4,
            cv2.LINE_AA,
        )
    if glare:
        center = (x + (width * 3) // 4, y + height // 2)
        cv2.ellipse(
            canvas,
            center,
            (max(20, width // 7), max(20, height // 5)),
            -15,
            0,
            360,
            (255, 255, 255),
            -1,
            cv2.LINE_AA,
        )


def _single_card_canvas(*, glare: bool = False) -> np.ndarray:
    canvas = np.full((800, 1200, 3), 30, dtype=np.uint8)
    points = np.array([[145, 125], [1060, 105], [1080, 675], [125, 695]], dtype=np.int32)
    _draw_card(canvas, points, glare=glare)
    return canvas


def _multiple_card_canvas() -> np.ndarray:
    canvas = np.full((800, 1400, 3), 30, dtype=np.uint8)
    left = np.array([[45, 205], [625, 205], [625, 565], [45, 565]], dtype=np.int32)
    right = np.array([[775, 205], [1355, 205], [1355, 565], [775, 565]], dtype=np.int32)
    _draw_card(canvas, left)
    _draw_card(canvas, right)
    return canvas


def _incomplete_card_canvas() -> np.ndarray:
    canvas = np.full((800, 1200, 3), 30, dtype=np.uint8)
    clipped = np.array([[-100, 135], [825, 135], [825, 695], [-100, 695]], dtype=np.int32)
    _draw_card(canvas, clipped)
    return canvas


class _TrackingUpload(BytesIO):
    name = "oversized.png"
    content_type = "image/png"

    def __init__(self, content: bytes):
        super().__init__(content)
        self.requested_read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.requested_read_sizes.append(size)
        return super().read(size)


class UploadValidationTests(SimpleTestCase):
    def test_accepts_supported_actual_formats_and_retains_original_bytes(self):
        formats = [("JPEG", "claimed.bin"), ("PNG", "claimed.txt")]
        if features.check("webp"):
            formats.append(("WEBP", "claimed.data"))

        for image_format, filename in formats:
            with self.subTest(image_format=image_format):
                upload = _pillow_upload((80, 50), image_format, name=filename)
                expected_bytes = bytes(upload.read())
                upload.seek(0)
                validated = validate_upload(upload, "front")
                self.assertEqual(validated.actual_format, image_format.lower())
                self.assertEqual(validated.original_bytes, expected_bytes)
                self.assertEqual(validated.image.shape, (50, 80, 3))
                self.assertFalse(np.shares_memory(validated.image, np.frombuffer(expected_bytes, dtype=np.uint8)))

    def test_missing_and_empty_uploads_are_bad_requests(self):
        for upload, expected_code in (
            (None, "missing_upload"),
            (SimpleUploadedFile("empty.png", b""), "empty_upload"),
        ):
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(KYCError) as raised:
                    validate_upload(upload, "front")
                self.assertEqual(raised.exception.http_status, 400)
                self.assertEqual(raised.exception.code, expected_code)

    @override_settings(KYC_MAX_UPLOAD_BYTES=32)
    def test_byte_read_is_bounded_and_reports_413(self):
        upload = _TrackingUpload(b"x" * 128)
        with self.assertRaises(KYCError) as raised:
            validate_upload(upload, "back")
        self.assertEqual(raised.exception.http_status, 413)
        self.assertEqual(raised.exception.code, "upload_too_large")
        self.assertLessEqual(max(upload.requested_read_sizes), 33)

    def test_unsupported_actual_format_reports_415(self):
        upload = _pillow_upload((80, 50), "GIF", name="looks-like.jpg")
        with self.assertRaises(KYCError) as raised:
            validate_upload(upload, "front")
        self.assertEqual(raised.exception.http_status, 415)
        self.assertEqual(raised.exception.code, "unsupported_image_format")

    def test_corrupt_content_reports_422(self):
        upload = SimpleUploadedFile("broken.jpg", b"not a real image", content_type="image/jpeg")
        with self.assertRaises(KYCError) as raised:
            validate_upload(upload, "front")
        self.assertEqual(raised.exception.http_status, 422)
        self.assertEqual(raised.exception.code, "image_decode_failed")

    def test_opencv_must_independently_decode_the_file(self):
        upload = _pillow_upload((80, 50), "PNG", name="valid.png")
        with patch("detector.uploads.cv2.imdecode", return_value=None):
            with self.assertRaises(KYCError) as raised:
                validate_upload(upload, "front")
        self.assertEqual(raised.exception.http_status, 422)
        self.assertEqual(raised.exception.details["decoder"], "opencv")

    def test_transparent_pixels_are_composited_before_processing(self):
        hidden_card = cv2.cvtColor(_single_card_canvas(), cv2.COLOR_BGR2RGBA)
        hidden_card[:, :, 3] = 0
        image = Image.fromarray(hidden_card, mode="RGBA")
        output = BytesIO()
        image.save(output, format="PNG")
        upload = SimpleUploadedFile("transparent.png", output.getvalue())

        validated = validate_upload(upload, "front")

        self.assertTrue(validated.transparency_composited)
        self.assertTrue(np.all(validated.image == 255))

    def test_multiframe_png_is_rejected_explicitly(self):
        first = Image.new("RGB", (80, 50), (10, 20, 30))
        second = Image.new("RGB", (80, 50), (40, 50, 60))
        output = BytesIO()
        first.save(
            output,
            format="PNG",
            save_all=True,
            append_images=[second],
            duration=100,
            loop=0,
        )

        with self.assertRaises(KYCError) as raised:
            validate_upload(SimpleUploadedFile("animated.png", output.getvalue()), "front")

        self.assertEqual(raised.exception.http_status, 415)
        self.assertEqual(raised.exception.code, "animated_image_not_supported")

    @override_settings(KYC_MAX_IMAGE_DIMENSION=100, KYC_MAX_IMAGE_PIXELS=100_000)
    def test_dimension_limit_reports_413(self):
        upload = _pillow_upload((101, 20), "PNG", name="wide.png")
        with self.assertRaises(KYCError) as raised:
            validate_upload(upload, "front")
        self.assertEqual(raised.exception.http_status, 413)
        self.assertEqual(raised.exception.code, "image_dimensions_exceeded")

    @override_settings(KYC_MAX_IMAGE_DIMENSION=1_000, KYC_MAX_IMAGE_PIXELS=2_000)
    def test_pixel_limit_reports_413(self):
        upload = _pillow_upload((50, 50), "PNG", name="many-pixels.png")
        with self.assertRaises(KYCError) as raised:
            validate_upload(upload, "front")
        self.assertEqual(raised.exception.http_status, 413)
        self.assertEqual(raised.exception.code, "image_pixel_limit_exceeded")

    def test_exif_orientation_is_applied_and_reported(self):
        upload = _pillow_upload(
            (40, 80),
            "JPEG",
            name="phone.jpg",
            exif_orientation=6,
        )
        validated = validate_upload(upload, "front")
        self.assertEqual((validated.encoded_width, validated.encoded_height), (40, 80))
        self.assertEqual((validated.width, validated.height), (80, 40))
        self.assertEqual(validated.image.shape, (40, 80, 3))
        self.assertTrue(validated.exif_transposed)
        self.assertEqual(validated.exif_rotation_degrees, 90)


@override_settings(
    KYC_MIN_CARD_AREA_RATIO=0.10,
    KYC_QUALITY_GATES_ENABLED=False,
    KYC_MIN_CARD_WIDTH=640,
    KYC_MIN_CARD_HEIGHT=400,
)
class PreprocessingTests(SimpleTestCase):
    def _validated(self, image: np.ndarray, side: str = "front"):
        return validate_upload(_cv_upload(image), side)

    def test_single_card_is_perspective_corrected_without_mutating_upload_image(self):
        validated = self._validated(_single_card_canvas())
        before = validated.image.copy()
        result = preprocess_document(validated, "front")

        self.assertTrue(np.array_equal(validated.image, before))
        self.assertEqual(result.detection.status, "single_card")
        self.assertEqual(result.detection.count, 1)
        self.assertEqual(result.side_signal, "unknown")
        self.assertEqual(result.card_rotation_degrees, 0)
        self.assertGreater(result.corrected_image.shape[1], result.corrected_image.shape[0])
        self.assertEqual(
            [finding.check for finding in result.quality_findings],
            ["blur", "exposure", "glare", "minimum_resolution"],
        )

    def test_portrait_card_is_rotated_and_rotation_is_reported(self):
        portrait = cv2.rotate(_single_card_canvas(), cv2.ROTATE_90_COUNTERCLOCKWISE)
        validated = self._validated(portrait)
        result = preprocess_document(validated, "front")
        self.assertEqual(result.card_rotation_degrees, 90)
        self.assertEqual(result.orientation_degrees, 90)
        self.assertGreater(result.corrected_image.shape[1], result.corrected_image.shape[0])

    def test_missing_card_has_specific_recapture_reason(self):
        blank = np.full((800, 1200, 3), 80, dtype=np.uint8)
        with self.assertRaises(KYCError) as raised:
            preprocess_document(self._validated(blank), "front")
        self.assertEqual(raised.exception.code, "card_not_found")
        self.assertEqual(raised.exception.http_status, 422)
        self.assertEqual(raised.exception.details["recapture_reasons"], ["card_not_detected"])

    def test_multiple_cards_are_rejected(self):
        with self.assertRaises(KYCError) as raised:
            preprocess_document(self._validated(_multiple_card_canvas()), "front")
        self.assertEqual(raised.exception.code, "multiple_cards_detected")
        self.assertEqual(raised.exception.details["recapture_reasons"], ["multiple_cards"])

    def test_card_cut_off_by_frame_is_rejected_as_incomplete(self):
        with self.assertRaises(KYCError) as raised:
            preprocess_document(self._validated(_incomplete_card_canvas()), "front")
        self.assertEqual(raised.exception.code, "incomplete_card")
        self.assertEqual(raised.exception.details["recapture_reasons"], ["card_outside_frame"])

    def test_model_detection_supplies_side_signal(self):
        validated = self._validated(_single_card_canvas(), side="back")
        result = preprocess_document(validated, "back", [{"label": "new_cnic_back"}])
        self.assertEqual(result.side_signal, "back")
        self.assertEqual(result.detection.model_detection_count, 1)

    def test_wrong_model_side_is_rejected(self):
        validated = self._validated(_single_card_canvas())
        with self.assertRaises(KYCError) as raised:
            preprocess_document(validated, "front", [{"class_name": "cnic_back"}])
        self.assertEqual(raised.exception.code, "wrong_document_side")
        self.assertEqual(raised.exception.details["recapture_reasons"], ["wrong_side"])

    @override_settings(
        KYC_QUALITY_GATES_ENABLED=True,
        KYC_BLUR_THRESHOLD=1_000_000_000.0,
        KYC_DARK_MEAN_THRESHOLD=0.0,
        KYC_BRIGHT_MEAN_THRESHOLD=255.0,
        KYC_GLARE_RATIO_THRESHOLD=1.0,
        KYC_MIN_CARD_WIDTH=1,
        KYC_MIN_CARD_HEIGHT=1,
    )
    def test_quality_gate_returns_findings_and_specific_reason(self):
        with self.assertRaises(KYCError) as raised:
            preprocess_document(self._validated(_single_card_canvas()), "front")
        self.assertEqual(raised.exception.code, "image_quality_insufficient")
        self.assertEqual(raised.exception.http_status, 422)
        self.assertIn("image_blurry", raised.exception.details["recapture_reasons"])
        self.assertEqual(len(raised.exception.details["quality_findings"]), 4)


class QualityMetricTests(SimpleTestCase):
    @override_settings(
        KYC_BLUR_THRESHOLD=80.0,
        KYC_DARK_MEAN_THRESHOLD=45.0,
        KYC_BRIGHT_MEAN_THRESHOLD=225.0,
        KYC_GLARE_RATIO_THRESHOLD=0.08,
        KYC_MIN_CARD_WIDTH=640,
        KYC_MIN_CARD_HEIGHT=400,
    )
    def test_quality_checks_report_blur_dark_glare_and_low_resolution(self):
        dark_small = np.full((100, 160, 3), 10, dtype=np.uint8)
        dark_findings = {finding.check: finding for finding in assess_quality(dark_small)}
        self.assertEqual(dark_findings["blur"].recapture_reason, "image_blurry")
        self.assertEqual(dark_findings["exposure"].recapture_reason, "image_too_dark")
        self.assertEqual(
            dark_findings["minimum_resolution"].recapture_reason,
            "card_resolution_too_low",
        )

        glare = np.full((500, 800, 3), 130, dtype=np.uint8)
        glare[:, :160] = 255
        glare_findings = {finding.check: finding for finding in assess_quality(glare)}
        self.assertEqual(glare_findings["glare"].recapture_reason, "excessive_glare")

from __future__ import annotations

import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase
from rest_framework import status

from .authentication import issue_organization_api_key
from .checks.base import DetectorInput, DetectorResult
from .checks.face import FaceComparisonDetector
from .document_types import mrz_check_digit, parse_td3_mrz
from .models import APIClientKey, DocumentArtifact, DuplicateFingerprint, ExtractionRevision, KYCApplication, Membership, Organization
from .object_storage import FileSystemObjectStore
from .policy import decide
from .tasks import process_application_task
from .errors import KYCError
from .webhooks import UnsafeWebhookURL, signature, validate_webhook_url


class DetectorContractTests(APITestCase):
    def test_common_result_rejects_score_without_score_type(self):
        with self.assertRaises(ValueError):
            DetectorResult("example", "completed", "pass", "1", score=0.7)

    @override_settings(
        KYC_FACE_DETECTOR_MODEL=Path("missing-yunet.onnx"),
        KYC_FACE_DETECTOR_SHA256="a" * 64,
        KYC_FACE_RECOGNITION_MODEL=Path("missing-sface.onnx"),
        KYC_FACE_RECOGNITION_SHA256="b" * 64,
    )
    def test_missing_face_models_are_unavailable_without_a_fabricated_score(self):
        image = np.zeros((500, 700, 3), dtype=np.uint8)
        result = FaceComparisonDetector().run(DetectorInput(front_image=image, selfie_image=image))
        self.assertEqual(result.execution_status, "unavailable")
        self.assertEqual(result.status, "unavailable")
        self.assertIsNone(result.score)

    @override_settings(KYC_REQUIRED_CHECKS=["document_consistency", "face_comparison"], KYC_POLICY_VERSION="test-policy")
    def test_unavailable_required_check_cannot_pass(self):
        decision = decide([
            {"detector": "document_consistency", "execution_status": "completed", "status": "pass", "reason_codes": []},
            {"detector": "face_comparison", "execution_status": "unavailable", "status": "unavailable", "reason_codes": ["weights_missing"]},
        ])
        self.assertEqual(decision.outcome, "needs_review")
        self.assertIn("required_check_unavailable:face_comparison", decision.reason_codes)

    def test_td3_mrz_pilot_validates_internal_check_digits_without_authenticity_claim(self):
        line1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
        base = "L898902C<" + mrz_check_digit("L898902C<") + "UTO" + "740812" + mrz_check_digit("740812") + "F" + "120415" + mrz_check_digit("120415") + "ZE184226B<<<<<" + mrz_check_digit("ZE184226B<<<<<")
        line2 = base + mrz_check_digit(base[0:10] + base[13:20] + base[21:43])
        result = parse_td3_mrz(line1, line2)
        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["authenticity_claimed"])


class SessionAuthenticationTests(APITestCase):
    def test_sign_in_requires_csrf_and_returns_membership(self):
        User = get_user_model()
        user = User.objects.create_user("csrf-user", email="csrf@example.invalid", password="strong-test-password")
        organization = Organization.objects.create(name="CSRF", slug="csrf")
        Membership.objects.create(organization=organization, user=user, role=Membership.Role.APPLICANT)
        client = APIClient(enforce_csrf_checks=True)
        payload = {"email": user.email, "password": "strong-test-password"}
        self.assertEqual(client.post("/api/v2/auth/sign-in", payload, format="json").status_code, 403)
        token = client.get("/api/v2/auth/csrf").json()["csrf_token"]
        response = client.post("/api/v2/auth/sign-in", payload, format="json", HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["memberships"][0]["organization_id"], str(organization.pk))

    @override_settings(CSRF_TRUSTED_ORIGINS=["http://127.0.0.1:5173"])
    def test_trusted_vite_origin_can_create_an_application(self):
        User = get_user_model()
        user = User.objects.create_user("vite-user", email="vite@example.invalid", password="strong-test-password")
        organization = Organization.objects.create(name="Vite", slug="vite")
        Membership.objects.create(organization=organization, user=user, role=Membership.Role.ADMIN)
        client = APIClient(enforce_csrf_checks=True)
        origin = "http://127.0.0.1:5173"
        token = client.get("/api/v2/auth/csrf", HTTP_ORIGIN=origin).json()["csrf_token"]
        response = client.post(
            "/api/v2/auth/sign-in",
            {"email": user.email, "password": "strong-test-password"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
            HTTP_ORIGIN=origin,
        )
        self.assertEqual(response.status_code, 200)
        token = client.cookies["csrftoken"].value
        response = client.post(
            "/api/v2/applications",
            {"external_reference": "browser-regression"},
            format="json",
            HTTP_X_CSRFTOKEN=token,
            HTTP_ORIGIN=origin,
        )
        self.assertEqual(response.status_code, 201)


class TenantAndReviewTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.reviewer = User.objects.create_user("reviewer", password="test-password-strong")
        self.other = User.objects.create_user("other", password="test-password-strong")
        self.org = Organization.objects.create(name="One", slug="one")
        self.other_org = Organization.objects.create(name="Two", slug="two")
        Membership.objects.create(organization=self.org, user=self.reviewer, role=Membership.Role.REVIEWER)
        Membership.objects.create(organization=self.other_org, user=self.other, role=Membership.Role.REVIEWER)
        self.application = KYCApplication.objects.create(organization=self.org, applicant=self.reviewer)
        self.other_application = KYCApplication.objects.create(organization=self.other_org, applicant=self.other)
        self.client.force_authenticate(self.reviewer)

    def test_application_queries_are_organization_scoped(self):
        response = self.client.get("/api/v2/applications")
        self.assertEqual(response.status_code, 200)
        identifiers = {item["id"] for item in response.json()["results"]}
        self.assertEqual(identifiers, {str(self.application.pk)})

    def test_reviewer_correction_preserves_raw_machine_revision(self):
        raw = ExtractionRevision.objects.create(application=self.application, field_name="name", raw_value="RAW", normalized_value="Raw", source=ExtractionRevision.Source.MACHINE)
        response = self.client.post(
            f"/api/v2/applications/{self.application.pk}/corrections",
            {"field_name": "name", "value": "Corrected", "reason": "source reviewed"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        raw.refresh_from_db()
        self.assertEqual(raw.raw_value, "RAW")
        correction = self.application.extractions.get(source=ExtractionRevision.Source.REVIEWER)
        self.assertEqual(correction.supersedes_id, raw.pk)

    def test_database_api_key_is_scoped_to_its_organization(self):
        _, key = issue_organization_api_key(self.org, "test", ["applications:read"])
        self.client.force_authenticate(user=None)
        response = self.client.get("/api/v2/applications", HTTP_X_API_KEY=key)
        self.assertEqual(response.status_code, 200)
        self.assertEqual({item["id"] for item in response.json()["results"]}, {str(self.application.pk)})

    def test_reviewer_assignment_stays_inside_organization(self):
        response = self.client.post(f"/api/v2/applications/{self.application.pk}/assignment", {"username": self.other.username}, format="json")
        self.assertEqual(response.status_code, 404)
        self.application.refresh_from_db()
        self.assertIsNone(self.application.assigned_to)

    def test_api_key_quota_is_enforced(self):
        _, key = issue_organization_api_key(self.org, "limited", ["applications:read"], quota_per_minute=1)
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get("/api/v2/applications", HTTP_X_API_KEY=key).status_code, 200)
        self.assertEqual(self.client.get("/api/v2/applications", HTTP_X_API_KEY=key).status_code, 429)


class RetentionTests(APITestCase):
    def test_expired_object_and_derived_identity_data_are_removed(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(KYC_OBJECT_STORAGE_ROOT=Path(directory) / "objects", KYC_OBJECT_STORAGE_BACKEND="filesystem"):
            User = get_user_model()
            user = User.objects.create_user("retention", password="test-password-strong")
            org = Organization.objects.create(name="Retention", slug="retention")
            application = KYCApplication.objects.create(organization=org, applicant=user)
            key = FileSystemObjectStore().put(str(org.pk), str(application.pk), "front", b"private-bytes", "application/octet-stream")
            artifact = DocumentArtifact.objects.create(application=application, kind="front", storage_key=key, content_type="image/jpeg", byte_size=13, sha256="a" * 64, expires_at=timezone.now() - timedelta(minutes=1))
            DuplicateFingerprint.objects.create(organization=org, application=application, artifact=artifact, sha256="a" * 64)
            ExtractionRevision.objects.create(application=application, field_name="cnic_number", raw_value="sensitive", normalized_value="sensitive", source=ExtractionRevision.Source.MACHINE)
            call_command("cleanup_application_data")
            artifact.refresh_from_db()
            self.assertIsNotNone(artifact.deleted_at)
            self.assertEqual(artifact.sha256, "")
            self.assertFalse(application.extractions.exists())
            self.assertFalse(Path(directory).joinpath("objects", *key.split("/")).exists())


class LivenessSessionTests(APITestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user("applicant", password="test-password-strong")
        self.org = Organization.objects.create(name="Applicant Org", slug="applicant-org")
        Membership.objects.create(organization=self.org, user=self.user, role=Membership.Role.APPLICANT)
        self.application = KYCApplication.objects.create(organization=self.org, applicant=self.user)
        self.client.force_authenticate(self.user)

    def test_consumed_manual_review_session_cannot_be_reused(self):
        created = self.client.post(f"/api/v2/applications/{self.application.pk}/liveness-sessions", {}, format="multipart")
        self.assertEqual(created.status_code, 201)
        body = created.json()
        first = self.client.post(f"/api/v2/liveness-sessions/{body['id']}/complete", {"challenge_token": body["challenge_token"], "manual_review": True}, format="json")
        self.assertEqual(first.status_code, 200)
        second = self.client.post(f"/api/v2/liveness-sessions/{body['id']}/complete", {"challenge_token": body["challenge_token"], "manual_review": True}, format="json")
        self.assertEqual(second.status_code, 409)
        self.assertEqual(second.json()["error"]["code"], "liveness_session_not_reusable")

    @override_settings(KYC_LIVENESS_SESSION_SECONDS=-1)
    def test_expired_session_is_rejected(self):
        created = self.client.post(f"/api/v2/applications/{self.application.pk}/liveness-sessions", {}, format="multipart").json()
        response = self.client.post(f"/api/v2/liveness-sessions/{created['id']}/complete", {"challenge_token": created["challenge_token"], "manual_review": True}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "liveness_session_expired")


class WebhookSecurityTests(APITestCase):
    def test_signature_covers_timestamp_and_exact_body(self):
        first = signature("secret", 1234, b'{"event":1}')
        self.assertEqual(first, signature("secret", 1234, b'{"event":1}'))
        self.assertNotEqual(first, signature("secret", 1235, b'{"event":1}'))
        self.assertNotEqual(first, signature("secret", 1234, b'{"event":2}'))

    @override_settings(KYC_WEBHOOK_ALLOW_HTTP=True)
    @patch("detector.webhooks.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 80))])
    def test_private_network_webhook_destination_is_rejected(self, _resolver):
        with self.assertRaises(UnsafeWebhookURL):
            validate_webhook_url("http://internal.example/callback")


@override_settings(KYC_REQUIRED_CHECKS=["document_consistency", "selfie_quality"])
class ProcessingPathTests(APITestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Processing", slug="processing")
        self.application = KYCApplication.objects.create(organization=self.org)
        for kind in ("front", "back", "selfie"):
            DocumentArtifact.objects.create(application=self.application, kind=kind, storage_key=f"{kind}-key", content_type="image/png", byte_size=10, width=800, height=500, sha256=kind.ljust(64, "0"))
        self.phase1 = {
            "extracted_fields": {},
            "field_evidence": {},
            "validation": {"checks": {}},
            "document": {"detected_sides": {}},
            "ocr": {"raw_detections": {"front": [], "back": []}},
        }
        self.pass_results = [
            {"detector": name, "execution_status": "completed", "status": "pass", "score": None, "threshold": None, "reason_codes": ["pass"], "evidence": [], "model_version": "test", "detector_version": "1", "execution_ms": 1, "experimental": False, "policy_relevant": True}
            for name in ("document_consistency", "selfie_quality")
        ]

    def _run(self, phase1=None, results=None):
        store = type("Store", (), {"get": lambda _self, _key: b"not-decoded-in-mocked-pipeline"})()
        with patch("detector.tasks.get_object_store", return_value=store), patch("detector.tasks.process_pair", return_value=phase1 or self.phase1), patch("detector.tasks.run_configured_detectors", return_value=results or self.pass_results):
            return process_application_task.run(str(self.application.pk))

    def test_successful_required_checks_complete(self):
        result = self._run()
        self.application.refresh_from_db()
        self.assertEqual(result["outcome"], "checks_passed")
        self.assertEqual(self.application.state, KYCApplication.State.COMPLETED)

    def test_unavailable_required_check_routes_to_review(self):
        results = [self.pass_results[0], {**self.pass_results[1], "execution_status": "unavailable", "status": "unavailable", "reason_codes": ["weights_missing"]}]
        result = self._run(results=results)
        self.assertEqual(result["outcome"], "needs_review")

    def test_phase1_recapture_error_becomes_completed_recapture(self):
        store = type("Store", (), {"get": lambda _self, _key: b"bytes"})()
        with patch("detector.tasks.get_object_store", return_value=store), patch("detector.tasks.process_pair", side_effect=KYCError("image_quality_insufficient", "recapture", status.HTTP_422_UNPROCESSABLE_ENTITY, {"recapture_reasons": ["blur"]})):
            result = process_application_task.run(str(self.application.pk))
        self.assertEqual(result["outcome"], "needs_recapture")

    def test_missing_artifact_becomes_failed_processing(self):
        self.application.artifacts.filter(kind="selfie").delete()
        result = process_application_task.run(str(self.application.pk))
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["error_code"], "required_artifact_missing")

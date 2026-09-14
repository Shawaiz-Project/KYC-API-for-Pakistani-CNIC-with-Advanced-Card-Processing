from __future__ import annotations

import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO, StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings
from PIL import Image

from detector.storage import (
    REQUEST_DIRECTORY_RE,
    RequestStorage,
    UnsafeStoragePathError,
    UnsupportedStoredImageError,
    cleanup_expired_request_directories,
    validate_storage_root,
)


def image_bytes(image_format: str, color: tuple[int, int, int]) -> bytes:
    stream = BytesIO()
    Image.new("RGB", (12, 8), color).save(stream, format=image_format)
    return stream.getvalue()


class RequestStorageTests(SimpleTestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "private-kyc"
        self.jpeg = image_bytes("JPEG", (20, 40, 60))
        self.png = image_bytes("PNG", (80, 100, 120))

    def test_storage_uses_random_request_directory_and_separate_copies(self) -> None:
        first = RequestStorage.create(root=self.root)
        second = RequestStorage.create(root=self.root)
        self.addCleanup(first.discard)
        self.addCleanup(second.discard)

        self.assertNotEqual(first.directory, second.directory)
        self.assertRegex(first.directory.name, REQUEST_DIRECTORY_RE)
        original = first.save_original("front", self.jpeg)
        processing = first.save_processing_copy("front", self.png)

        self.assertEqual(original.name, "front.jpg")
        self.assertEqual(processing.name, "front.png")
        self.assertEqual(original.parent.name, "originals")
        self.assertEqual(processing.parent.name, "processing")
        self.assertEqual(original.read_bytes(), self.jpeg)
        self.assertEqual(processing.read_bytes(), self.png)

    def test_extension_comes_from_actual_decoded_format(self) -> None:
        storage = RequestStorage.create(root=self.root)
        self.addCleanup(storage.discard)

        png_path = storage.save_original("back", self.png)

        self.assertEqual(png_path.suffix, ".png")
        with self.assertRaises(UnsupportedStoredImageError):
            storage.save_original("front", b"not an image")

    def test_side_names_and_duplicate_writes_are_rejected(self) -> None:
        storage = RequestStorage.create(root=self.root)
        self.addCleanup(storage.discard)
        path = storage.save_original("front", self.jpeg)

        with self.assertRaises(FileExistsError):
            storage.save_original("front", self.jpeg)
        with self.assertRaises(ValueError):
            storage.save_original("../identity-number", self.jpeg)

        self.assertEqual(path.read_bytes(), self.jpeg)
        self.assertEqual([item.name for item in path.parent.iterdir()], ["front.jpg"])

    def test_concurrent_writes_to_one_slot_are_exclusive(self) -> None:
        storage = RequestStorage.create(root=self.root)
        self.addCleanup(storage.discard)

        def attempt_write(_: int) -> bool:
            try:
                storage.save_original("front", self.jpeg)
            except FileExistsError:
                return False
            return True

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(attempt_write, range(16)))

        self.assertEqual(sum(results), 1)
        stored = storage.directory / "originals" / "front.jpg"
        self.assertEqual(stored.read_bytes(), self.jpeg)

    def test_concurrent_requests_never_share_paths_or_bytes(self) -> None:
        payloads = [image_bytes("PNG", (index, 0, 0)) for index in range(20)]

        def save(index: int) -> tuple[Path, Path, bytes]:
            storage = RequestStorage.create(root=self.root)
            path = storage.save_original("front", payloads[index])
            return storage.directory, path, path.read_bytes()

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(save, range(len(payloads))))

        directories = [directory for directory, _, _ in results]
        self.assertEqual(len(set(directories)), len(payloads))
        for index, (directory, path, stored) in enumerate(results):
            self.assertRegex(directory.name, re.compile(r"\Akyc-[0-9a-f]{32}\Z"))
            self.assertEqual(path.parent.parent, directory)
            self.assertEqual(stored, payloads[index])

    @override_settings(KYC_PRESERVE_UPLOADS=False)
    def test_context_manager_discards_when_preservation_is_disabled(self) -> None:
        with override_settings(KYC_PRIVATE_STORAGE_ROOT=self.root):
            with RequestStorage.create() as storage:
                directory = storage.directory
                storage.save_original("front", self.jpeg)
                self.assertTrue(directory.exists())

        self.assertFalse(directory.exists())

    def test_validate_root_rejects_broad_and_non_directory_targets(self) -> None:
        with self.assertRaises(UnsafeStoragePathError):
            validate_storage_root(Path(self.root.anchor))

        file_root = Path(self.temporary_directory.name) / "ordinary-file"
        file_root.write_text("not a directory", encoding="utf-8")
        with self.assertRaises(UnsafeStoragePathError):
            validate_storage_root(file_root)


class RetentionCleanupTests(SimpleTestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name) / "private-kyc"
        self.root.mkdir()

    def make_request_directory(self) -> Path:
        storage = RequestStorage.create(root=self.root)
        return storage.directory

    def test_cleanup_removes_only_expired_direct_request_directories(self) -> None:
        now = 2_000_000_000.0
        expired = self.make_request_directory()
        boundary = self.make_request_directory()
        fresh = self.make_request_directory()
        unrelated = self.root / "do-not-delete"
        unrelated.mkdir()
        unowned_lookalike = self.root / f"kyc-{'b' * 32}"
        unowned_lookalike.mkdir()
        nested_parent = self.root / "nested"
        nested_parent.mkdir()
        nested = nested_parent / f"kyc-{'a' * 32}"
        nested.mkdir()

        os.utime(expired, (now - 3601, now - 3601))
        os.utime(boundary, (now - 3600, now - 3600))
        os.utime(fresh, (now - 3599, now - 3599))
        os.utime(unrelated, (now - 7200, now - 7200))
        os.utime(unowned_lookalike, (now - 7200, now - 7200))
        os.utime(nested, (now - 7200, now - 7200))

        result = cleanup_expired_request_directories(
            root=self.root, retention_hours=1, now=now
        )

        self.assertEqual(result.removed, 1)
        self.assertFalse(expired.exists())
        self.assertTrue(boundary.exists())
        self.assertTrue(fresh.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(unowned_lookalike.exists())
        self.assertTrue(nested.exists())

    def test_dry_run_reports_without_deleting(self) -> None:
        now = 2_000_000_000.0
        expired = self.make_request_directory()
        os.utime(expired, (now - 7200, now - 7200))

        result = cleanup_expired_request_directories(
            root=self.root, retention_hours=1, dry_run=True, now=now
        )

        self.assertEqual(result.expired, 1)
        self.assertEqual(result.removed, 0)
        self.assertTrue(expired.exists())

    def test_missing_root_is_a_safe_noop_and_negative_retention_is_rejected(self) -> None:
        missing = Path(self.temporary_directory.name) / "missing" / "private-kyc"
        result = cleanup_expired_request_directories(root=missing, retention_hours=1)
        self.assertEqual(result.scanned, 0)

        with self.assertRaises(ValueError):
            cleanup_expired_request_directories(root=self.root, retention_hours=-1)

    @override_settings(KYC_RETENTION_HOURS=1)
    def test_management_command_dry_run_uses_configured_root(self) -> None:
        expired = self.make_request_directory()
        old = 1_000_000_000.0
        os.utime(expired, (old, old))
        output = StringIO()

        with override_settings(KYC_PRIVATE_STORAGE_ROOT=self.root):
            call_command("cleanup_kyc_uploads", dry_run=True, stdout=output)

        self.assertTrue(expired.exists())
        self.assertIn("would remove 1 expired request directory", output.getvalue())

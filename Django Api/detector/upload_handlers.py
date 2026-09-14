"""Streaming request-size enforcement for multipart file content."""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.core.files.uploadhandler import FileUploadHandler


class TotalUploadLimitHandler(FileUploadHandler):
    """Reject aggregate file bytes even when Content-Length is unavailable."""

    chunk_size = 64 * 1024

    def __init__(self, request=None):
        super().__init__(request)
        self._received_bytes = 0

    def receive_data_chunk(self, raw_data, start):
        self._received_bytes += len(raw_data)
        if self._received_bytes > int(settings.KYC_MAX_REQUEST_BYTES):
            raise RequestDataTooBig("Multipart file content exceeded the configured limit.")
        return raw_data

    def file_complete(self, file_size):
        return None

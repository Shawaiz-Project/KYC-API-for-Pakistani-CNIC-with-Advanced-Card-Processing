# Phase 1 API contract

All processing requests use `multipart/form-data`, require the configured API
key header (default `X-API-Key`), and are throttled. Health endpoints are public.
Responses echo a valid, non-CNIC-shaped caller `X-Request-ID` (1–64 safe
characters) or generate a UUID. The response header and body ID match.
Processing and readiness responses include `Cache-Control: no-store`.

## Endpoints

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/health/live` | no | Process liveness; never loads models. |
| `GET` | `/health/ready` | no | Sanitized secrets/storage/model readiness; loads each configured model once per worker without exposing weight manifests. |
| `POST` | `/api/v1/kyc/process` | API key | Canonical structured Phase 1 contract. |
| `POST` | `/api/v1/card/detector` | API key | Historical compatibility adapter, no trailing slash. |

The canonical request fields are:

| Field | Required | Meaning |
| --- | --- | --- |
| `front` | yes | Actual JPEG, PNG, or WebP front capture. |
| `back` | yes | Actual JPEG, PNG, or WebP back capture. |
| `template` | no | `auto` (default), `generic`, `smart`, `smart_card`, `nicop`, or `legacy_urdu`. |

The configured byte, aggregate streaming request, file-count, form-field,
pixel, and dimension limits are applied before model inference. Declared MIME
type and filename do not override decoded content. Images must contain exactly
one frame. PNG/WebP alpha is composited onto an opaque white background so
hidden RGB pixels cannot create a card that was invisible to the submitter.

## Canonical successful processing response

HTTP success means the pipeline completed. It does not mean verification passed.
This shortened synthetic response shows the shape:

```json
{
  "request_id": "onboarding-42",
  "api_version": "v1",
  "processing": {
    "success": true,
    "status": "completed",
    "duration_ms": 412.7
  },
  "verification": {
    "decision": "uncertain",
    "authoritative_issuance_checked": false,
    "message": "Local extraction and syntax checks are not proof of issuance, authenticity, or bearer identity."
  },
  "document": {
    "type": "pakistani_cnic",
    "layout": "generic",
    "layout_status": "uncertain",
    "detected_sides": {
      "front_upload": {
        "detected_side": "front",
        "status": "pass",
        "confidence": {
          "value": 0.75,
          "type": "heuristic_score",
          "calibrated": false
        },
        "signals": {
          "face_count": 1,
          "qr_count": 0,
          "front_keyword_count": 0,
          "back_keyword_count": 0
        }
      },
      "back_upload": {
        "detected_side": "unknown",
        "status": "uncertain",
        "confidence": {
          "value": 0.0,
          "type": "heuristic_score",
          "calibrated": false
        },
        "signals": {
          "face_count": 0,
          "qr_count": 0,
          "front_keyword_count": 0,
          "back_keyword_count": 0
        }
      }
    },
    "detections": {
      "front": [
        {
          "status": "single_card",
          "count": 1,
          "source": "opencv_contour",
          "polygon": [[12.0, 18.0], [842.0, 20.0], [840.0, 520.0], [10.0, 518.0]],
          "area_ratio": 0.71,
          "complete": true,
          "model_detection_count": 0,
          "score": {
            "value": 0.71,
            "type": "heuristic_area_ratio",
            "calibrated": false
          }
        }
      ],
      "back": []
    }
  },
  "quality": {
    "overall_status": "pass",
    "front": [
      {
        "check": "blur",
        "status": "pass",
        "value": 132.4,
        "threshold": {"minimum_laplacian_variance": 80.0},
        "message": "The card has sufficient edge detail."
      }
    ],
    "back": []
  },
  "extracted_fields": {
    "name": {
      "raw_value": "SYNTHETIC EXAMPLE",
      "normalized_value": "SYNTHETIC EXAMPLE",
      "supported": true
    },
    "guardian_name": {"raw_value": null, "normalized_value": null, "supported": true},
    "gender": {"raw_value": null, "normalized_value": null, "supported": true},
    "country_of_stay": {"raw_value": null, "normalized_value": null, "supported": true},
    "cnic_number": {
      "raw_value": "00000-0000000-0",
      "normalized_value": "00000-0000000-0",
      "supported": true
    },
    "date_of_birth": {"raw_value": null, "normalized_value": null, "supported": true},
    "date_of_issue": {"raw_value": null, "normalized_value": null, "supported": true},
    "date_of_expiry": {"raw_value": null, "normalized_value": null, "supported": true}
  },
  "field_evidence": {
    "name": [
      {
        "side": "front",
        "raw_text": "Name: SYNTHETIC EXAMPLE",
        "normalized_text": "Name: SYNTHETIC EXAMPLE",
        "raw_value": "SYNTHETIC EXAMPLE",
        "normalized_value": "SYNTHETIC EXAMPLE",
        "bbox": [[90.0, 80.0], [430.0, 80.0], [430.0, 112.0], [90.0, 112.0]],
        "confidence": {
          "value": 0.88,
          "type": "raw_ocr_score",
          "calibrated": false
        },
        "source": "inline_label"
      }
    ]
  },
  "ocr": {
    "engine": "EasyOCR",
    "status": "available",
    "raw_detections": {"front": [], "back": []},
    "ordering": "top_to_bottom_with_per_line_unicode_direction",
    "rotation_candidates_degrees": [180]
  },
  "validation": {
    "overall_status": "fail",
    "checks": {
      "cnic_syntax": {
        "status": "pass",
        "code": "cnic_syntax_valid",
        "message": "The CNIC has canonical 5-7-1 syntax. Issuance and authenticity were not checked."
      },
      "issuance": {
        "status": "not_run",
        "code": "issuance_not_checked",
        "message": "Issuance and bearer identity require an authoritative external verification source."
      }
    }
  },
  "model_versions": {
    "card_boundary": {
      "name": "opencv-contour-baseline",
      "version": "4.11.0.86",
      "kind": "deterministic_heuristic"
    },
    "ocr": {
      "name": "EasyOCR",
      "version": "1.7.2",
      "languages": ["en", "ur"],
      "device": "cpu",
      "confidence": "raw_model_score_not_calibrated_probability",
      "weights": []
    }
  }
}
```

Every canonical field is present. `raw_value` preserves OCR evidence;
`normalized_value` may normalize Unicode compatibility forms, Urdu/Persian
digits, whitespace, CNIC hyphens, and unambiguous full dates. It is `null` when
unreadable. It never contains inferred missing characters.

When OCR is intentionally optional but cannot load, processing may still
complete with `ocr.status: unavailable`; unreadable supported fields then add
`availability: unavailable`, and dependent checks use the `unavailable` status.

Bounding boxes are four pixel-coordinate `[x, y]` points in the perspective-
corrected card image. Raw OCR/detector scores, contour area ratios, and side
heuristics explicitly carry `calibrated: false`.

## Check status vocabulary

Every validation/quality check uses one of:

- `pass`: the local check's explicit condition passed;
- `fail`: the local check's explicit condition failed;
- `uncertain`: evidence exists but is inconclusive;
- `not_run`: a prerequisite/source was absent or the check is intentionally not performed;
- `unavailable`: the configured component cannot run.

`processing.success`, `verification.decision`, and individual validation checks
are separate. Issuance always remains `not_run` in Phase 1.

## Structured errors

Canonical errors use:

```json
{
  "request_id": "onboarding-42",
  "error": {
    "code": "image_quality_insufficient",
    "message": "The front image does not meet capture-quality requirements.",
    "details": {
      "expected_side": "front",
      "recapture_reasons": ["image_blurry", "card_resolution_too_low"]
    }
  }
}
```

Common status/code pairs:

| HTTP | Code examples |
| --- | --- |
| 400 | `missing_document_side`, `empty_upload`, `invalid_upload`, `unsupported_document_layout` |
| 401 | `authentication_required`, `invalid_api_key`, `authentication_unavailable` |
| 405 | `method_not_allowed` |
| 413 | `request_too_large`, `upload_too_large`, `image_dimensions_exceeded`, `image_pixel_limit_exceeded` |
| 415 | `unsupported_request_media_type`, `unsupported_image_format`, `animated_image_not_supported` |
| 422 | `image_decode_failed`, `card_not_found`, `multiple_cards_detected`, `incomplete_card`, `wrong_document_side`, `image_quality_insufficient` |
| 429 | `rate_limited` |
| 500 | `internal_error`, `processing_copy_failed` |
| 503 | `model_unavailable` |

Model errors contain a component and safe reason, for example:

```json
{
  "request_id": "onboarding-42",
  "error": {
    "code": "model_unavailable",
    "message": "The required OCR model is unavailable.",
    "details": {
      "component": "OCR",
      "reason": "weights_missing_or_invalid",
      "exception_type": "FileNotFoundError"
    }
  }
}
```

## Legacy adapter

`POST /api/v1/card/detector` accepts only `front_imagee` and `back_image` and
retains these six nominal success keys:

```json
{
  "Name": "...",
  "Gaurdian Name": "...",
  "Id Card Number": "...",
  "Data Of Birth": "...",
  "Data Of Issue": "...",
  "Data Of Expiry": "..."
}
```

A detected cross-side CNIC mismatch retains the historical HTTP 406 body:

```json
{"error":"FRONT SIDE & BACK SIDE OF THE CARD ARE NOT SAME"}
```

Authentication, throttling, upload validation, quality gates, and required
model availability now apply to this route. These security corrections are
intentional; the URL, request field names, nominal response keys, and deliberate
mismatch response remain compatible.

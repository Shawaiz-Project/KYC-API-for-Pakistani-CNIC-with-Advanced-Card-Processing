# Project Report

## KYC API for Pakistani CNIC with Advanced Card Processing

**Project Type:** Artificial Intelligence / Machine Learning / Computer Vision / OCR / REST API
**Domain:** Digital Identity & KYC
**Primary Technologies:** Python, Django REST Framework, OpenCV, EasyOCR, Machine Learning, React, TypeScript
**Supported Documents:** Pakistani CNIC, Smart CNIC, and NICOP
**Processing Mode:** Front + Back Identity Document Processing

---

# 1. Executive Summary

This project focuses on the design and development of a **privacy-conscious KYC document-processing API for Pakistani identity cards**. The system accepts images of the **front and back sides** of an identity document and processes them through a multi-stage computer-vision and OCR pipeline.

The primary objective is to automate the early stages of a KYC workflow by detecting the identity-card region, validating image quality and document structure, identifying the document format, extracting available textual information, and performing deterministic consistency checks.

The system is designed to support multiple Pakistani identity-document layouts, including:

* Traditional CNIC layouts containing Urdu text
* Smart CNIC / Smart ID Card layouts
* NICOP (National Identity Card for Overseas Pakistanis)

The architecture combines **image processing, computer vision, OCR, structured information extraction, validation rules, API security, and privacy-oriented storage controls**.

A fundamental design principle of the project is the distinction between **document processing** and **identity verification**. The API can extract and validate information contained in submitted documents, but it does not claim to independently verify CNIC issuance, identity ownership, or authenticity against NADRA or another authoritative government source.

---

# 2. Problem Statement

Traditional identity-document processing often requires manual inspection of uploaded documents. This creates several challenges:

* Manual document review is time-consuming.
* Image quality varies significantly between users.
* Documents may be rotated, cropped, blurred, overexposed, or affected by glare.
* Pakistani identity documents exist in multiple layouts and generations.
* Urdu and English text require different OCR considerations.
* Front and back images contain different but related information.
* Raw OCR output is not directly suitable for structured KYC workflows.
* Sensitive identity documents require careful handling and controlled retention.

Therefore, there is a need for an automated processing pipeline capable of converting raw CNIC images into **structured, validated, and reviewable KYC signals** while maintaining strict boundaries around what the system can and cannot verify.

---

# 3. Project Objectives

The major objectives were:

### Primary Objectives

1. Develop a RESTful KYC API capable of accepting CNIC front and back images.
2. Detect and isolate the identity-card region from uploaded images.
3. Correct common image-orientation and perspective problems.
4. Perform document-quality and sanity checks.
5. Identify supported Pakistani identity-document formats.
6. Extract relevant information using OCR.
7. Normalize and structure OCR output.
8. Validate extracted fields using deterministic rules.
9. Compare information across front and back images.
10. Provide structured API responses suitable for downstream KYC systems.
11. Protect sensitive identity-document data through private, request-scoped processing.
12. Provide a foundation for future liveness, fraud-detection, reviewer, and policy workflows.

### Secondary Objectives

* Provide reproducible local development.
* Support automated testing without real identity documents.
* Provide OpenAPI documentation.
* Maintain backward compatibility with the legacy API surface.
* Prepare the architecture for production deployment using PostgreSQL, Redis, and private object storage.

---

# 4. Supported Document Types

The system is designed around multiple Pakistani identity-document formats.

## 4.1 Traditional CNIC

Traditional CNIC layouts may contain significant Urdu text and require specialized OCR handling.

Potential fields include:

* CNIC number
* Name
* Father's / Guardian's name
* Date of birth
* Date of issue
* Date of expiry

Field availability depends on the document layout and OCR quality.

---

## 4.2 Smart CNIC / Smart ID Card

Smart-card layouts contain a different visual and textual arrangement from traditional CNICs.

The processing pipeline therefore treats smart cards as a distinct document schema rather than assuming a single universal layout.

---

## 4.3 NICOP

NICOP documents are processed through a dedicated schema where supported.

The system does not assume that every field exists in every identity-document variant.

---

# 5. System Architecture

The project follows a modular processing architecture:

```text
                 ┌───────────────────────┐
                 │   Client Application   │
                 │ React / TypeScript UI  │
                 └───────────┬───────────┘
                             │
                             ▼
                 ┌───────────────────────┐
                 │     Django REST API   │
                 │ Authentication / API  │
                 └───────────┬───────────┘
                             │
                             ▼
                 ┌───────────────────────┐
                 │ Input Validation      │
                 │ Format / Size / Bytes │
                 └───────────┬───────────┘
                             │
                             ▼
                 ┌───────────────────────┐
                 │ Image Preprocessing   │
                 │ EXIF / Rotation /     │
                 │ Perspective / Resize  │
                 └───────────┬───────────┘
                             │
                             ▼
                 ┌───────────────────────┐
                 │ Card Detection        │
                 │ ML / OpenCV Baseline  │
                 └───────────┬───────────┘
                             │
                             ▼
                 ┌───────────────────────┐
                 │ Document Classification│
                 │ CNIC / Smart / NICOP  │
                 └───────────┬───────────┘
                             │
                             ▼
                 ┌───────────────────────┐
                 │ OCR Engine             │
                 │ English + Urdu         │
                 └───────────┬───────────┘
                             │
                             ▼
                 ┌───────────────────────┐
                 │ Field Extraction       │
                 │ Parsing / Normalization│
                 └───────────┬───────────┘
                             │
                             ▼
                 ┌───────────────────────┐
                 │ Validation &           │
                 │ Cross-Side Consistency │
                 └───────────┬───────────┘
                             │
                             ▼
                 ┌───────────────────────┐
                 │ Structured KYC Result │
                 └───────────────────────┘
```

---

# 6. Core Features

## 6.1 Card Region Detection

The first stage identifies the probable identity-card region within the submitted image.

The project supports two detection approaches:

### Machine Learning Detector

A trained detector can be configured to identify the card boundary using a dedicated identity-card dataset.

### OpenCV Baseline

When a custom detector is not configured, the system explicitly uses:

```text
opencv-contour-baseline
```

This distinction is important because the baseline should not be presented as equivalent to a trained production detector.

The original detector weights are not reconstructed or fabricated when they are unavailable.

---

# 7. Image Preprocessing

Uploaded images pass through several preprocessing stages.

### Input validation

The system checks:

* file content
* supported image format
* byte size
* image dimensions
* pixel count
* decoder validity
* multi-frame images

Supported formats include:

```text
JPEG
PNG
WebP
```

Transparent pixels in supported images can be composited onto a white background before processing.

---

## 7.1 Orientation Correction

The system handles:

* EXIF orientation
* rotated images
* 180-degree document orientation
* normalized landscape presentation

This improves the reliability of downstream detection and OCR.

---

## 7.2 Perspective Correction

When a card is photographed at an angle, the system attempts to identify the card boundaries and perform a perspective transformation.

Conceptually:

```text
Original Image
      │
      ▼
Card Boundary Detection
      │
      ▼
Corner Identification
      │
      ▼
Perspective Transformation
      │
      ▼
Normalized Card Image
```

---

# 8. Image Quality Assessment

Before OCR, the system evaluates image suitability.

Potential findings include:

* excessive blur
* insufficient resolution
* overexposure
* underexposure
* glare
* incomplete card visibility
* incorrect orientation
* multiple detected cards

These findings can be used to recommend image recapture.

Importantly, image-quality findings are **processing signals**, not proof that a document is fraudulent.

---

# 9. Card Classification

The system uses document characteristics to determine which processing schema should be applied.

Supported schema identifiers include:

```text
generic
smart
smart_card
nicop
legacy_urdu
```

Classification allows the extraction pipeline to adapt to different document layouts instead of applying one fixed OCR strategy to every card.

---

# 10. OCR Pipeline

The OCR subsystem provides text recognition from the normalized document image.

The baseline implementation uses:

**EasyOCR 1.7.2**

Configured languages:

```text
English
Urdu
```

The OCR pipeline supports:

* raw OCR text
* bounding boxes
* raw OCR scores
* Unicode normalization
* digit normalization
* right-to-left ordering
* Urdu text handling
* 180-degree OCR fallback

---

# 11. Structured Data Extraction

Raw OCR output is converted into structured fields.

Example conceptual output:

```json
{
  "document_type": "smart",
  "cnic_number": "xxxxx-xxxxxxx-x",
  "name": null,
  "guardian_name": null,
  "date_of_issue": null,
  "date_of_expiry": null
}
```

If the system cannot reliably identify a field, the field remains:

```json
null
```

The system deliberately avoids inventing missing characters or filling unavailable information.

---

# 12. CNIC Validation

The validation layer applies deterministic rules to extracted values.

Examples include:

### Format validation

```text
xxxxx-xxxxxxx-x
```

### Date validation

* valid date format
* logical date ordering
* issue date versus expiry date
* lifetime/no-expiry handling

### Required-field validation

Fields can be checked according to the selected document schema.

### Cross-side consistency

Information extracted from the front and back images can be compared where corresponding fields are expected.

---

# 13. Important Verification Boundary

The system intentionally distinguishes between:

### What the API can establish

* The uploaded file is a supported image.
* A card-like region was detected.
* OCR identified certain text.
* A value matches a syntactic format.
* Two extracted values are consistent.
* The image satisfies or fails defined quality checks.

### What the API cannot establish by itself

* Whether NADRA issued the CNIC.
* Whether the CNIC belongs to the applicant.
* Whether the applicant is the person shown on the document.
* Whether the document is officially valid.
* Whether a document is definitively authentic.
* Whether an OCR confidence score represents a calibrated probability.

No NADRA verification or CNIC checksum is claimed by this implementation.

---

# 14. API Security

Because identity documents are highly sensitive, the API includes multiple security controls.

### Authentication

Sensitive endpoints require API-key authentication.

### Request IDs

Requests can include:

```http
X-Request-ID: onboarding-42
```

This allows operational tracing without putting identity information into log messages.

### Throttling

Request throttling helps limit abuse and excessive processing.

### Structured Errors

Failures are returned through structured API responses instead of leaking internal exception details.

---

# 15. Privacy Architecture

The project follows a privacy-conscious processing model.

### Storage controls

Uploaded files:

* use randomized storage paths
* never use client filenames as storage paths
* are stored in private request-scoped directories
* separate original and processed copies
* are not exposed through public media URLs

### Logging controls

Logs do not contain:

* CNIC numbers
* OCR text
* identity-document images
* QR payloads
* biometric information
* client filenames

Only operational lifecycle and error metadata are retained.

---

# 16. Data Retention

Identity-document files should not remain indefinitely.

The project provides an explicit cleanup operation:

```bash
python main.py cleanup_kyc_uploads --dry-run
```

After review:

```bash
python main.py cleanup_kyc_uploads
```

Production deployments should execute cleanup through an external scheduler according to the organization's documented retention policy.

---

# 17. Technology Stack

## Backend

* Python 3.11
* Django
* Django REST Framework
* OpenCV
* EasyOCR
* PyTorch
* ONNX Runtime
* NumPy
* Pillow

## Frontend

* React
* TypeScript
* Vite
* Modern browser APIs

## Infrastructure

* PostgreSQL
* Redis
* Private object storage
* Background workers
* Reverse proxy / TLS
* Docker/containerized deployment

---

# 18. Development Methodology

The project follows a modular pipeline architecture so individual components can be improved independently.

For example:

```text
Detection
    ↓
Preprocessing
    ↓
Classification
    ↓
OCR
    ↓
Parsing
    ↓
Validation
    ↓
Policy
```

This architecture allows future models to replace individual components without rewriting the complete API.

---

# 19. Challenges

Several technical challenges were identified during development.

## 19.1 Multiple Card Layouts

Pakistani identity documents exist in multiple formats and generations.

A single extraction template therefore cannot reliably handle every document.

**Solution:** schema-specific extraction and classification.

---

## 19.2 Image Quality

Real-world users may submit:

* low-resolution images
* photographs at an angle
* rotated images
* blurred images
* images containing reflections
* partially cropped documents

**Solution:** preprocessing and image-quality gates before OCR.

---

## 19.3 Urdu OCR

Urdu introduces additional complexity because of:

* right-to-left writing
* connected glyphs
* font variation
* OCR segmentation challenges
* mixed Urdu/English layouts

**Solution:** Urdu-capable OCR, Unicode normalization, RTL ordering, and structured parsing.

---

## 19.4 OCR Uncertainty

OCR output is inherently probabilistic and can contain incorrect characters.

**Solution:** never silently manufacture missing characters and expose raw OCR information separately from deterministic validation.

---

## 19.5 Detector Availability

The original trained detector weights were not available for reconstruction.

**Solution:** retain an explicit detector interface and provide an OpenCV contour-based baseline rather than falsely claiming equivalent model performance.

---

# 20. Testing Strategy

The test suite is designed to avoid the use of real identity documents.

Synthetic and in-memory fixtures are used wherever possible.

Testing covers:

* image validation
* corrupted files
* unsupported formats
* size restrictions
* image dimensions
* EXIF orientation
* rotation
* missing cards
* multiple cards
* incomplete cards
* quality gates
* OCR parsing
* Unicode/Urdu ordering
* field validation
* authentication
* structured errors
* model lifecycle
* private storage
* retention cleanup
* response serialization
* legacy API compatibility

---

# 21. Evaluation Methodology

For a production-quality evaluation, the system should be assessed using an authorized, held-out dataset.

Recommended evaluation dimensions include:

| Component             | Suggested Metric       |
| --------------------- | ---------------------- |
| Card detection        | Precision, Recall, IoU |
| Classification        | Accuracy, Macro-F1     |
| OCR                   | CER, WER               |
| Field extraction      | Precision, Recall, F1  |
| CNIC parsing          | Exact-match accuracy   |
| Quality detection     | Precision/Recall       |
| Cross-side validation | Precision/Recall       |
| API                   | p50/p95/p99 latency    |
| Resource usage        | CPU/RAM/GPU            |
| Failure handling      | Error-class coverage   |

All identity-document datasets must be collected, stored, processed, and evaluated under appropriate authorization and security controls.

---

# 22. Results

The implementation successfully establishes a functional KYC document-processing pipeline covering:

* image validation
* card preprocessing
* card-region detection
* document-schema handling
* OCR
* structured extraction
* deterministic validation
* cross-side consistency checks
* authenticated API access
* private request-scoped storage
* structured errors
* health endpoints
* automated testing

However, **numerical accuracy claims should only be reported after evaluation against an authorized held-out dataset**.

Therefore, this report does not claim a specific OCR accuracy, detector accuracy, authenticity-detection accuracy, or identity-verification accuracy without reproducible benchmark evidence.

This distinction ensures that engineering functionality is not incorrectly presented as empirical model performance.

---

# 23. Future Enhancements

## 23.1 Advanced Detection

* Dedicated CNIC object-detection model
* Improved card-boundary detection
* Multi-document detection
* Better perspective estimation

## 23.2 Advanced OCR

* PaddleOCR comparison
* transformer-based OCR
* Urdu-specific OCR models
* layout-aware OCR
* field-specific recognition models

## 23.3 Fraud and Tamper Analysis

Future versions can investigate signals such as:

* image manipulation
* inconsistent compression patterns
* suspicious editing artifacts
* duplicate documents
* template inconsistencies
* document/selfie consistency

These should be treated as **risk signals** and validated against an appropriately labeled dataset.

## 23.4 Liveness

A future liveness workflow could introduce:

```text
Applicant
    ↓
Liveness Session
    ↓
Challenge / Capture
    ↓
Face Detection
    ↓
Anti-Spoofing Model
    ↓
Liveness Signal
```

Such a system requires dedicated evaluation against presentation attacks before being relied upon operationally.

---

# 24. Production Roadmap

### Phase 1 — Document Processing

* Image validation
* Card detection
* Perspective correction
* OCR
* Field extraction
* CNIC syntax validation
* API security
* Private storage
* Testing

### Phase 2 — KYC Intelligence

* Detector contracts
* Document/selfie consistency
* Liveness sessions
* Duplicate detection
* Tamper-review signals
* Policy engine

### Phase 3 — Operational Platform

* Multi-tenancy
* PostgreSQL persistence
* Redis task processing
* Reviewer dashboard
* Applicant portal
* Background workers
* Private object storage
* Signed webhooks
* Monitoring
* Audit workflows
* Containerized deployment

---

# 25. Security and Compliance Considerations

This project is a technical KYC-processing implementation and should not automatically be interpreted as a legally compliant KYC product.

Before processing real identity documents in production, an organization should conduct appropriate:

* security assessment
* threat modeling
* penetration testing
* privacy assessment
* access-control review
* data-retention review
* incident-response planning
* third-party license review
* regulatory/legal assessment

The deployment organization is responsible for determining the applicable requirements for its specific use case.

---

# 26. Conclusion

The **Pakistani CNIC KYC API** establishes a modular foundation for automated identity-document processing using computer vision, OCR, structured extraction, and deterministic validation.

The project addresses several practical challenges associated with Pakistani identity documents, including multiple document layouts, image-quality variation, perspective distortion, Urdu OCR, front/back consistency, and sensitive-data handling.

The resulting architecture provides a foundation that can evolve from a document-processing API into a broader KYC workflow platform incorporating liveness, document/selfie consistency, fraud-review signals, reviewer workflows, background processing, and policy-based decisioning.

Most importantly, the system maintains a clear distinction between **observation, extraction, validation, and identity verification**. This prevents OCR output or machine-learning signals from being incorrectly represented as definitive evidence of identity or document authenticity.

The project therefore provides a technically extensible foundation for future research and production engineering in **AI-assisted identity-document processing and KYC automation**.

---

## Project Status

**Current focus:** Privacy-conscious Pakistani identity-document processing

**Core capabilities:**
`Computer Vision → OCR → Extraction → Validation → API → Secure Processing`

**Future direction:**
`KYC Processing → Risk Signals → Liveness → Review → Policy → Production Platform`

---

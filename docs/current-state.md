# Current-state audit

> Phase 2/3 update (2026-09-19): the historical findings below describe the
> audited starting point. The repository now also contains the implementation
> summarized in `phase-2-completion.md` and `phase-3-completion.md`. Required
> external assets remain absent: EasyOCR weights, the original custom CNIC
> detector, YuNet/SFace files and approved provenance, a landmark/anti-spoof
> package, consented grouped evaluation/attack data, PostgreSQL/Redis runtime,
> object-store/provider credentials, and public deployment/TLS approval.

Audit date: 2026-09-14  
Scope: the workspace as supplied, before Phase 1 changes

## Audit boundaries

- No applicable `AGENTS.md` exists in this workspace or its visible parent tree.
- The workspace is not a Git checkout: `.git` is absent and `git status` fails.
  Consequently, tracked/untracked state, history, and unrelated local edits cannot
  be established from metadata. Existing files were treated as user-owned.
- The audit did not use the identity-card images as test fixtures and did not
  transcribe or log their contents.

## Repository inventory as found

| Area | Contents | State before Phase 1 |
| --- | --- | --- |
| Root prototype | `main.py` | Standalone experimental pipeline; not runnable from the checked-out paths. |
| Django service | `Django Api/api`, `Django Api/detector` | One POST route; startup failed on imports. |
| Detector wrapper | `yolov8/` | Generic ONNX inference and drawing code; no weight file. |
| Data | `Dataset/` and root screenshots | A few unlabeled, real-looking identity documents/results; no provenance, consent, annotations, or split manifest. |
| Dependencies | `Requirements.txt` | Python import statements rather than pip requirements. |
| Tests | `Django Api/detector/tests.py` | Empty Django scaffold. |
| Evaluation | none | No runner, ground truth, metric definitions, or baseline result. |

No `.onnx`, `.pt`, `.pth`, `.ckpt`, `.weights`, `.engine`, or `.tflite`
model weight was present. The EasyOCR model cache was also absent on the audited
machine.

## Existing API contract

The only route was:

```text
POST /api/v1/card/detector
Content-Type: multipart/form-data
```

It had no trailing slash and accepted these exact multipart names:

```text
front_imagee   # historical typo is part of the contract
back_image
```

The nominal success response was HTTP 200 with six flat string values:

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

The spelling of `Gaurdian` and `Data` is historical. A nominal front/back CNIC
mismatch returned HTTP 406:

```json
{"error":"FRONT SIDE & BACK SIDE OF THE CARD ARE NOT SAME"}
```

All other bad inputs commonly became unhandled server errors. There was no
authentication requirement, throttle, request ID, structured error envelope,
health endpoint, or readiness endpoint.

## What was actually implemented

- An ONNX YOLOv8-style inference wrapper and drawing helpers existed.
- A Haar-cascade face lookup was used as a front-side precondition.
- Two English-only EasyOCR readers were created per request for fixed,
  face-relative upper/lower regions.
- OpenCV/pyzbar QR decoding took a fixed substring from a back payload.
- A front/back string equality check was labelled as CNIC validity.
- A six-key response dictionary was assembled on the narrow happy path.

## Broken or unsafe behavior as found

- `python "Django Api/manage.py" check` failed because the sibling `yolov8`
  package was not importable. EasyOCR, pyzbar, and ONNX Runtime were also absent
  on the audited machine.
- `../Model/best.onnx` was hard-coded in three request-time functions, but the
  file and its `Model/` directory did not exist.
- Three detector sessions and two OCR readers were constructed for each request.
- The front image was converted to grayscale and then passed to code that
  unconditionally expected three BGR channels.
- Zero/multiple detections, no face, short OCR output, malformed/no QR, missing
  upload, and decode failure led to unpacking, indexing, unbound-variable, or
  OpenCV exceptions.
- Detection drew on the full input; it did not extract a card or correct its
  perspective.
- OCR fields were selected by list position. OCR boxes and scores were dropped.
- Urdu OCR, Unicode/digit normalization, layout templates, side classification,
  quality checks, date/CNIC syntax checks, and expiry handling were absent.
- A process-CWD `IdCardData.csv` was truncated on every successful request.
  Concurrent requests could overwrite each other. The CSV writer iterated
  dictionary keys rather than extracted values.
- Names and CNIC-related values were printed. Secrets and debug mode were
  hard-coded in Django settings.
- Originals were not retained in application-controlled private storage, and no
  retention cleanup existed.

## README claims not supported by repository evidence

The pre-Phase-1 README claimed robust/accurate card-region detection trained on
a comprehensive or diverse dataset; three CNIC formats; smart/old-card
classification; Urdu extraction; logo/landmark checks; EasyOCR or PaddleOCR;
and reliable, secure verification with satisfactory accuracy. The repository
did not contain the weights, training configuration, class map, PaddleOCR code,
Urdu reader configuration, evaluation set, measurements, or security controls
needed to substantiate those claims. The six detector labels in
`yolov8/utils.py` were all the same `ID CARD` string.

## Required external assets

### EasyOCR baseline

For `en,ur`, EasyOCR 1.7.2 selects its CRAFT text detector and Arabic-script
recognizer. An offline deployment must supply the files that the pinned EasyOCR
release expects in `KYC_OCR_MODEL_DIR`. Phase 1 provides an explicit warm-up
command and a SHA-256 manifest command; automatic runtime downloads are disabled
by default. Upstream EasyOCR also verifies its published model files with its
own embedded MD5 values.

### Optional custom card detector

The original `best.onnx` is missing. To enable a custom detector, an operator
must supply all of:

1. the ONNX weight file;
2. its acquisition/provenance record and redistribution license;
3. its exact SHA-256 value;
4. class names and supported front/back/template semantics;
5. the input/output and preprocessing contract;
6. training/evaluation dataset provenance and version.

Until then, Phase 1 uses and identifies a deterministic OpenCV contour baseline.
It must not be described as the missing trained detector.

### Held-out evaluation data

An acceptable manifest needs paired front/back paths, expected fields, Urdu
transcriptions, document/side labels, card boxes or polygons, and opaque
`person_group_id` plus `document_group_id`. Every image for one person/document
must belong to exactly one split. Real documents must be stored outside Git with
documented consent, access controls, retention, and license/provenance.

## Exact measurement blockers at audit time

| Metric | Status | Missing evidence |
| --- | --- | --- |
| Field exact-match accuracy | `not_run` | Held-out field truth and usable OCR weights |
| Urdu character error rate | `not_run` | Urdu transcription truth and usable OCR weights |
| Card detection performance | `not_run` | Detector weight (for trained baseline) and box/polygon truth |
| End-to-end latency | `not_run` | Loadable production models and representative held-out inputs |
| Peak memory | `not_run` | Loadable production models and representative held-out inputs |
| Regression comparison | `unavailable` | A completed initial baseline result with matching manifest/model IDs |

The files originally under `Dataset/` appear unsuitable for a public repository:
they are unredacted, real-looking identity records, and no authorization or
license accompanies them. They were preserved because this workspace has no Git
metadata and the task requires unrelated/user-owned files to be preserved. They
must be reviewed by the data owner and removed from current files and repository
history before any public release.

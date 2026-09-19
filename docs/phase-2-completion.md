# Phase 2 completion report

## Working integrations

- A common detector interface reports execution state, check status, optional
  typed raw score, reasons, evidence references, model/detector versions, and
  execution time. Detectors are enabled through `KYC_ENABLED_DETECTORS`.
- Document consistency reuses Phase 1 side classification and identifier
  comparisons and reports repeated/wrong/uncertain sides as evidence.
- Selfie quality checks decoded content, minimum dimensions, blur, exposure,
  and face count using a named OpenCV baseline.
- Face comparison integrates OpenCV YuNet + SFace only when both configured
  files match operator-supplied SHA-256 values. Missing assets return
  `unavailable` with `score: null`.
- Short-lived liveness sessions are application/user bound, randomized,
  challenge-token protected, expiring, and single-use. Manual review is an
  explicit accessible alternative.
- Cryptographic file hashes and perceptual dHash signals are organization
  scoped. Identifier HMAC support is disabled until a secret and sufficiently
  reliable normalized OCR value are available. Duplicate signals never reject
  by themselves.
- Tamper edge-density is explicitly experimental, reviewer-only, and never
  proof of forgery.
- The policy separates processing from decisions and prevents unavailable or
  uncertain required checks from passing. Django admin and the React reviewer
  workspace expose evidence and historical revisions.

## Not validated / intentionally unavailable

- No face weights are bundled. YuNet's model directory declares MIT licensing,
  but SFace pretrained-weight commercial/provenance clarification remains an
  operator legal-review blocker. Exact acquired files and SHA-256 values must be
  recorded before enabling.
- No server-side landmark model or evaluated anti-spoof model is configured.
  Therefore action capture cannot become a production liveness pass. It routes
  to manual review; printed-photo/screen-video resistance is not claimed.
- Barcode data is compared only when Phase 1 recognizes documented CNIC syntax;
  opaque payload semantics are not guessed.
- Portrait/logo/chip/signature/text landmark classifiers and localized tamper
  models require layout-specific annotated data. The global tamper heuristic is
  review-only and is unreliable for photocopies, recompression, screenshots,
  and unfamiliar templates.
- There is no consented representative face, document, or presentation-attack
  evaluation corpus in this repository. `benchmarks/phase2-result.json`
  therefore reports `not_run`; no FMR, FNMR, attack acceptance, genuine-user
  rejection, tamper false-positive, or duplicate-error accuracy is claimed.

## Verification performed

- Backend tests cover detector result invariants, missing models without fake
  scores, unavailable required-check policy, organization isolation, API-key
  scope, immutable raw OCR correction, liveness expiry/replay, webhook signing,
  and internal-network rejection.
- The evaluator enforces identity-group isolation across training, calibration,
  and final evaluation and reports Wilson 95% intervals and subgroup sample
  sizes. See [evaluation-phase2.md](evaluation-phase2.md).

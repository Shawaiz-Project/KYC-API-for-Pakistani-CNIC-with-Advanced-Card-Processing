# Threshold and policy inventory

All numeric model outputs are raw signals, not calibrated probabilities. A
threshold is operational only for the named model/version, preprocessing,
document layout, and workflow in which it was calibrated.

| Signal | Default | Purpose | Validation status |
| --- | ---: | --- | --- |
| Document blur | Laplacian variance >= 80 | Recapture gate | Engineering baseline only |
| Dark exposure | mean luminance >= 45 | Recapture gate | Engineering baseline only |
| Bright exposure | mean luminance <= 225 | Recapture gate | Engineering baseline only |
| Glare | saturated-area ratio <= 0.08 | Recapture gate | Engineering baseline only |
| Card area | contour area ratio >= 0.12 | Boundary completeness | Engineering baseline only |
| Selfie minimum dimension | 480 px | Recapture gate | Engineering baseline only |
| YuNet face detection | raw score >= 0.85 | Candidate face selection | Upstream baseline; local evaluation missing |
| SFace cosine similarity | 0.363 | Initial match boundary | Upstream example only; local calibration missing |
| SFace uncertainty margin | +/- 0.04 | Route near-boundary cases to review | Policy baseline only |
| Identifier OCR reliability | max raw OCR score >= 0.85 | Permit keyed HMAC comparison | Uncalibrated gate; review required |

`KYC_REQUIRED_CHECKS` defines workflow requirements. A required detector must
finish with `pass`; disabled, unavailable, execution-failed, uncertain, or fail
results cannot produce `checks_passed`. Experimental tamper and duplicate
signals have `policy_relevant: false` and cannot reject an applicant alone.

Before automatic biometric/liveness/tamper decisions, select thresholds using a
separate calibration split, freeze them, then evaluate once on the final split
using [evaluation-phase2.md](evaluation-phase2.md). Record selected thresholds,
sample sizes, uncertainty intervals, model checksums, and subgroup results.

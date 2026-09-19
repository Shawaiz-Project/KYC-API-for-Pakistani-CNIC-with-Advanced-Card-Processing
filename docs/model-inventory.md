# Model and detector inventory

| Component | Version/source | Asset present | Runtime behavior | Capability status |
| --- | --- | --- | --- | --- |
| Card boundary | OpenCV 4.11 contour baseline | code only | available on CPU | Working engineering baseline; not trained/evaluated detector |
| Optional CNIC detector | external ONNX | no | optional fallback or unavailable if required | Blocked by weights/license/schema/evaluation |
| OCR | EasyOCR 1.7.2, CRAFT + Arabic recognizer | no weights in Git | unavailable until explicitly provisioned; once loaded, cached per worker | Working integration; accuracy not measured here |
| Selfie face count | OpenCV Haar baseline | packaged XML | available | Quality heuristic only |
| Face landmarks/detection | OpenCV Zoo YuNet | no | checksum-gated optional adapter | Integration implemented; local licensing/evaluation blocked |
| Face recognition | OpenCV Zoo SFace | no | checksum-gated optional adapter | Integration implemented; exact weight license/provenance/evaluation blocked |
| Liveness action tracking | YuNet five landmarks | no | unavailable without verified YuNet | Integration implemented; not anti-spoofing |
| Anti-spoofing | separately evaluated model required | no | unavailable; no fabricated score | Not integrated because contract/license/evaluation absent |
| Tampering | OpenCV edge-density heuristic | code only | completed, experimental, review-only | Not validated; not proof of forgery |
| Duplicate file/similarity | SHA-256 + dHash | code only | completed, organization-scoped | Working review signal |
| Identifier duplicate | HMAC-SHA256 | secret required | only for syntax-valid OCR >= configured gate | Working privacy mechanism; OCR gate uncalibrated |
| Authoritative verification | provider interface | no provider/credentials | unavailable | Not integrated; never simulated |

Model files are ignored by Git. Acquisition, exact license, source URL/commit,
date, byte size, SHA-256, tensor contract, preprocessing, thresholds, and final
evaluation result belong in a deployment-controlled provenance record.

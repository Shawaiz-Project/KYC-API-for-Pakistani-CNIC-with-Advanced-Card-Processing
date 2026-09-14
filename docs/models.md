# Model acquisition, integrity, and loading

Phase 1 has two independent detection layers:

1. an always-available OpenCV contour baseline for card boundaries; and
2. optional external model assets for OCR and a custom ONNX card detector.

No trained CNIC detector weight was included in the audited workspace. Never
rename an unrelated model to `best.onnx` or claim it is the original model.

## EasyOCR English/Urdu baseline

The pinned EasyOCR 1.7.2 package supports the `en,ur` combination using its
Arabic-script generation-1 recognizer plus CRAFT detector. EasyOCR is licensed
Apache-2.0 at the project level; review its acknowledgements and the terms of
the pretrained artifacts before redistribution:

- source/license: <https://github.com/JaidedAI/EasyOCR>
- model configuration: <https://github.com/JaidedAI/EasyOCR/blob/v1.7.2/easyocr/config.py>

The pinned upstream configuration names these files and validates them using
the embedded MD5 values below:

| Purpose | File | Upstream release asset | Upstream MD5 |
| --- | --- | --- | --- |
| Text detection | `craft_mlt_25k.pth` | `pre-v1.1.6/craft_mlt_25k.zip` | `2f8227d2def4037cdb3b34389dcf9ec1` |
| English/Urdu recognition | `arabic.pth` | `pre-v1.1.6/arabic.zip` | `993074555550e4e06a6077d55ff0449a` |

Production should acquire these during an explicit build/provisioning step,
not from inside an API request. With the virtual environment active:

```powershell
$env:KYC_OCR_MODEL_DIR = "D:\private-models\easyocr"
python "Django Api/manage.py" warm_ocr_models --allow-download
python "Django Api/manage.py" model_manifest
```

The warm-up command lets EasyOCR perform its upstream integrity check. The
manifest command emits local SHA-256 hashes; capture that output in deployment
provenance and compare it after every transfer. API-time downloads default to
off (`KYC_OCR_DOWNLOAD_ENABLED=false`). Offline deployments can copy the two
verified `.pth` files into `KYC_OCR_MODEL_DIR` and run `model_manifest` before
starting workers.

The reader is created lazily at most once in each worker process and then
shared behind an inference lock. Readiness attempts the same load and returns a
specific, non-sensitive reason such as `easyocr_not_installed` or
`weights_missing_or_invalid`.

## Optional custom ONNX card detector

Configure a detector only after its owner supplies provenance and license:

```dotenv
KYC_CARD_DETECTOR_MODEL=D:/private-models/cnic-card-detector.onnx
KYC_CARD_DETECTOR_SHA256=<64 lowercase hex characters>
KYC_CARD_DETECTOR_REQUIRED=true
```

Generate the checksum without loading the model:

```powershell
Get-FileHash -Algorithm SHA256 D:\private-models\cnic-card-detector.onnx
```

The service refuses to load a configured model when its SHA-256 is absent or
does not match. A missing optional model falls back to the named contour
baseline; a missing required model makes readiness and processing unavailable.
The legacy YOLO wrapper is guarded because it stores mutable inference state.

The original repository provides none of the following, so the custom detector
remains an external blocker:

- acquisition URL or owner;
- redistribution/model license;
- SHA-256 checksum;
- class-name/side/template mapping;
- training data provenance and version;
- supported input/output tensor contract;
- held-out performance report.

## CPU and GPU selection

`KYC_DEVICE=cpu` is the tested default. The service explicitly selects ONNX
Runtime's CPU execution provider and asks EasyOCR/PyTorch to use CPU.

`KYC_DEVICE=auto` uses CUDA only when the installed runtimes expose it.
`KYC_DEVICE=cuda` is strict: readiness fails instead of silently falling back if
CUDA is unavailable. Install only one of `onnxruntime` or `onnxruntime-gpu` in
an environment. GPU builds additionally require a mutually compatible NVIDIA
driver, CUDA, cuDNN, PyTorch, and ONNX Runtime combination; follow ONNX Runtime's
current provider matrix: <https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html>.

## Response provenance

Successful v1 responses report the model/package version, device, and weight
SHA-256 values loaded by that worker. OCR and detector scores are labelled raw,
uncalibrated scores. They are not probabilities of identity, authenticity, or
correct issuance.

# Phase 2 evaluation protocol

`python main.py evaluate_phase2 --manifest <private.csv> --output <result.json>`
consumes predictions/labels, not raw images. Start with
`benchmarks/phase2-manifest-schema.csv`; keep the completed file outside Git.

Required controls:

1. Obtain explicit consent and document collection purpose, geography, capture
   devices, card versions, demographic coverage, and attack construction.
2. Assign every image/video belonging to one person or document the same opaque
   `identity_group`. The evaluator rejects any group crossing training,
   threshold-calibration, or final-evaluation splits.
3. Select face/liveness thresholds using calibration only. Freeze model,
   preprocessing, policy, and threshold versions before final evaluation.
4. Report face false-match/non-match, liveness attack acceptance/genuine
   rejection, tamper false positives, and duplicate false positives/negatives
   with sample sizes and 95% Wilson intervals.
5. Break sample sizes/results down by supported card type and capture condition.
   Do not enable automatic decisions for undersized or unsupported groups.
6. Record latency and peak RSS per case on named hardware. At least 20 final
   latency samples are required before the script emits p95.

The checked-in `benchmarks/phase2-result.json` is an honest blocker report,
not a benchmark. It must not be replaced by synthetic accuracy claims.

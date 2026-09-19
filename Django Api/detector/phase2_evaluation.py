from __future__ import annotations

import csv
import json
import math
import platform
import statistics
from collections import defaultdict
from pathlib import Path


def wilson(successes: int, total: int, z: float = 1.96) -> dict:
    if total == 0:
        return {"rate": None, "count": 0, "interval_95": [None, None]}
    rate = successes / total
    denominator = 1 + z * z / total
    centre = (rate + z * z / (2 * total)) / denominator
    spread = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return {"rate": rate, "count": total, "errors": successes, "interval_95": [max(0, centre - spread), min(1, centre + spread)]}


def _rate(rows: list[dict], label_column: str, label: str, decision_column: str, error_decision: str) -> dict:
    relevant = [row for row in rows if row.get(label_column) == label]
    return wilson(sum(row.get(decision_column) == error_decision for row in relevant), len(relevant))


def evaluate_manifest(path: Path) -> dict:
    if not path.is_file():
        return {"status": "not_run", "blockers": [f"evaluation_manifest_missing:{path}", "consented_representative_evaluation_data_missing", "face_and_anti_spoof_model_weights_missing"]}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return {"status": "not_run", "blockers": ["evaluation_manifest_has_no_rows", "no_accuracy_or_latency_claim_can_be_made"]}
    groups: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        groups[row.get("identity_group", "")].add(row.get("split", ""))
    leaks = sorted(group for group, splits in groups.items() if group and len(splits) > 1)
    if leaks:
        return {"status": "invalid", "blockers": ["identity_leakage_between_splits"], "leaking_group_count": len(leaks)}
    evaluation = [row for row in rows if row.get("split") == "evaluation"]
    if not evaluation:
        return {"status": "not_run", "blockers": ["final_evaluation_split_missing"]}
    metrics = {
        "face_false_match_rate": _rate(evaluation, "face_label", "mismatch", "face_decision", "match"),
        "face_false_non_match_rate": _rate(evaluation, "face_label", "genuine", "face_decision", "non_match"),
        "liveness_attack_acceptance_rate": _rate(evaluation, "liveness_label", "attack", "liveness_decision", "pass"),
        "liveness_genuine_rejection_rate": _rate(evaluation, "liveness_label", "genuine", "liveness_decision", "fail"),
        "tampering_false_positive_rate": _rate(evaluation, "tamper_label", "genuine", "tamper_decision", "flagged"),
        "duplicate_false_positive_rate": _rate(evaluation, "duplicate_label", "unique", "duplicate_decision", "duplicate"),
        "duplicate_false_negative_rate": _rate(evaluation, "duplicate_label", "duplicate", "duplicate_decision", "unique"),
    }
    latencies = [float(row["latency_ms"]) for row in evaluation if row.get("latency_ms")]
    memory = [float(row["peak_rss_mb"]) for row in evaluation if row.get("peak_rss_mb")]
    breakdown = defaultdict(int)
    for row in evaluation:
        breakdown[(row.get("card_type", "unspecified"), row.get("capture_condition", "unspecified"))] += 1
    return {
        "status": "completed",
        "sample_size": len(evaluation),
        "split_counts": {name: sum(row.get("split") == name for row in rows) for name in ("training", "calibration", "evaluation")},
        "metrics": metrics,
        "performance": {
            "latency_p95_ms": statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else None,
            "latency_sample_size": len(latencies),
            "peak_rss_mb_max": max(memory) if memory else None,
            "hardware": platform.platform(),
        },
        "breakdown_sample_sizes": [{"card_type": key[0], "capture_condition": key[1], "count": count} for key, count in sorted(breakdown.items())],
        "limitations": ["Rates are meaningful only if the supplied manifest is consented, representative, independently held out, and labels were quality controlled.", "Raw detector confidence is not treated as a calibrated probability."],
    }


def write_result(result: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

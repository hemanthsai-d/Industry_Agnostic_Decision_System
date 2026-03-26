from __future__ import annotations


def compute_evidence_score(scores: list[float]) -> float:
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 4)


def compute_final_confidence(
    route_conf: float,
    evidence_score: float,
    escalation_prob: float,
    ood_score: float,
    contradiction_score: float,
) -> float:
    escalation_safe = 1.0 - escalation_prob
    final = (
        (0.45 * route_conf)
        + (0.25 * evidence_score)
        + (0.20 * escalation_safe)
        - (0.07 * ood_score)
        - (0.03 * contradiction_score)
    )
    return round(max(0.0, min(1.0, final)), 4)


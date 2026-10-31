"""
Root Cause Rules
-------------------
Pure, if/else rule-based scoring logic for ranking probable root
causes of an incident. Uses live z-score data from Prometheus
alongside graph proximity and corroborating incident signals.

Functions here take already-fetched plain Python data as arguments
(a list of graph edges, a set of currently-open-incident service
names, a dict of live z-scores) rather than calling out to
Prometheus/incident-engine/dependency-graph themselves -- that I/O
orchestration lives in main.py, keeping this file pure and easy
to test in isolation, no network required.
"""

from dataclasses import dataclass, field

# Z-score threshold above which a service's latency is considered
# suspiciously elevated (same scale as zscore_detector.py).
ZSCORE_SUSPICION_THRESHOLD = 2.0


@dataclass
class CauseScore:
    service_name: str
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def add(self, amount: float, reason: str) -> None:
        self.score += amount
        self.reasons.append(reason)


def rule_self_service(scores: dict[str, CauseScore], affected_service: str) -> None:
    """
    The affected service itself is always a candidate cause of its own
    incident.
    """
    scores.setdefault(affected_service, CauseScore(affected_service)).add(
        0.3, "the affected service itself"
    )


def rule_graph_neighbors(
    scores: dict[str, CauseScore],
    affected_service: str,
    predecessors: list[str],
    successors: list[str],
) -> None:
    """
    Direct neighbors in the dependency graph are plausible causes.
    Successors (downstream) are weighted higher than predecessors.
    """
    for predecessor in predecessors:
        scores.setdefault(predecessor, CauseScore(predecessor)).add(
            0.15, f"calls into {affected_service} (upstream caller)"
        )
    for successor in successors:
        scores.setdefault(successor, CauseScore(successor)).add(
            0.35, f"{affected_service} depends on it (downstream call)"
        )


def rule_concurrent_open_incidents(scores: dict[str, CauseScore], open_incident_services: set[str]) -> None:
    """
    Any candidate that ALSO currently has its own open incident gets
    a boost -- real corroborating evidence from incident-engine.
    """
    for candidate in list(scores.keys()):
        if candidate in open_incident_services:
            scores[candidate].add(0.3, "currently has its own open incident")


def rule_elevated_latency_zscores(scores: dict[str, CauseScore], latency_zscores: dict[str, float]) -> None:
    """
    Any candidate whose live latency z-score exceeds the suspicion
    threshold gets a boost proportional to how far above the threshold
    it is. Uses the same adaptive baseline approach as
    zscore_detector.py -- no hardcoded per-service thresholds needed.
    """
    for candidate in list(scores.keys()):
        zscore = latency_zscores.get(candidate)
        if zscore is not None and zscore > ZSCORE_SUSPICION_THRESHOLD:
            scores[candidate].add(
                min(0.35, 0.15 + (zscore - ZSCORE_SUSPICION_THRESHOLD) * 0.05),
                f"elevated latency z-score ({zscore:.2f} > {ZSCORE_SUSPICION_THRESHOLD})"
            )


def rank_probable_causes(
    affected_service: str,
    predecessors: list[str],
    successors: list[str],
    open_incident_services: set[str],
    latency_zscores: dict[str, float],
    top_n: int = 5,
) -> list[dict]:
    """
    Runs every rule above, in order, accumulating a score and a list
    of human-readable reasons per candidate service. Scores are capped
    at 0.95, then candidates are sorted highest-first and truncated.
    """
    scores: dict[str, CauseScore] = {}

    rule_self_service(scores, affected_service)
    rule_graph_neighbors(scores, affected_service, predecessors, successors)
    rule_concurrent_open_incidents(scores, open_incident_services)
    rule_elevated_latency_zscores(scores, latency_zscores)

    ranked = sorted(scores.values(), key=lambda c: c.score, reverse=True)

    return [
        {
            "service_name": cause.service_name,
            "probability": round(min(cause.score, 0.95), 2),
            "reasons": cause.reasons,
        }
        for cause in ranked[:top_n]
    ]
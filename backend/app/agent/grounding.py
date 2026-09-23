"""Evidence grounding for agent output (Phase 4).

Every evidence item the agent proposes must trace to a real rule finding or a
metric statistic present in the Vehicle Health Context. Items that cannot be
grounded are removed, and the removal is recorded as a validation warning so
operations can see how much the model stayed on-rails.
"""

from __future__ import annotations

from app.agent.schemas import EvidenceItem
from app.intelligence.models import Finding, HealthContext

# Relative tolerance when matching a proposed observed value against the latest
# known metric value from the context statistics.
_VALUE_TOLERANCE = 0.10


def ground_evidence(
    proposed: list[EvidenceItem],
    context: HealthContext | None,
) -> tuple[list[EvidenceItem], list[str]]:
    """Return (grounded_evidence, validation_warnings)."""
    if not proposed:
        return [], []
    if context is None:
        return [], ["No evidence was grounded: no Vehicle Health Context is available"]

    grounded: list[EvidenceItem] = []
    warnings: list[str] = []
    seen: set[tuple[str, str]] = set()

    for item in proposed:
        matched = _match_finding(item, context)
        if matched is None:
            matched = _match_metric(item, context)
        if matched is None:
            warnings.append(
                f"Evidence dropped (not grounded in context): rule_id={item.rule_id!r} metric={item.metric!r}"
            )
            continue
        key = (matched.rule_id or "", matched.metric or "")
        if key in seen:
            continue
        seen.add(key)
        grounded.append(matched)

    return grounded, warnings


def _match_finding(item: EvidenceItem, context: HealthContext) -> EvidenceItem | None:
    for finding in context.findings:
        if item.rule_id and finding.rule_id == item.rule_id:
            return _from_finding(finding, message=item.message or finding.message)
    return None


def _match_metric(item: EvidenceItem, context: HealthContext) -> EvidenceItem | None:
    if not item.metric or item.metric not in context.statistics:
        return None
    stats = context.statistics[item.metric]
    last = stats.last
    if last is None or item.observed_value is None:
        return None
    tolerance = max(abs(last) * _VALUE_TOLERANCE, 0.001)
    if abs(item.observed_value - last) <= tolerance:
        return EvidenceItem(
            rule_id=None,
            metric=item.metric,
            observed_value=item.observed_value,
            threshold=item.threshold,
            unit=stats.unit,
            message=item.message or f"Metric near latest reported value for {item.metric}",
            severity=None,
        )
    return None


def _from_finding(finding: Finding, *, message: str) -> EvidenceItem:
    return EvidenceItem(
        rule_id=finding.rule_id,
        metric=finding.metric,
        observed_value=finding.observed_value,
        threshold=finding.threshold,
        unit=finding.unit,
        message=message,
        severity=finding.severity,
    )


def critical_rule_ids(context: HealthContext | None) -> list[str]:
    """Rule ids of the critical findings in the context (used for deduplication)."""
    if context is None:
        return []
    return [finding.rule_id for finding in context.findings if finding.severity == "critical"]

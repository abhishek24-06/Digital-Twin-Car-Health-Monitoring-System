"""Deterministic rule engine producing factual telemetry findings.

All thresholds are centralized in :class:`RuleThresholds`. Findings describe
telemetry-derived evidence only and never claim a mechanical diagnosis —
e.g. "coolant temperature is elevated" is allowed, "the water pump has failed"
is not.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.intelligence.models import (
    AnalysisWindow,
    DataQuality,
    Finding,
    MetricStatistics,
)

INSUFFICIENT_DATA_RULE = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class RuleThresholds:
    """Centralized configuration for all health rules (single source of truth)."""

    coolant_max_warning: float = 100.0
    coolant_max_critical: float = 110.0
    oil_max_warning: float = 100.0
    oil_max_critical: float = 110.0
    rapid_temp_rise_celsius: float = 8.0
    battery_min_warning: float = 12.0
    battery_min_critical: float = 10.5
    battery_max_warning: float = 15.0
    engine_load_mean_warning: float = 40.0
    engine_load_mean_critical: float = 60.0
    rpm_mean_warning: float = 4500.0
    fuel_min_warning: float = 15.0
    fuel_min_critical: float = 5.0
    gap_multiplier: float = 3.0
    coverage_minimum: float = 0.5


class HealthRuleEngine:
    """Evaluates analysed telemetry context into structured findings."""

    def __init__(self, thresholds: RuleThresholds | None = None) -> None:
        self._t = thresholds or RuleThresholds()

    def evaluate(
        self,
        *,
        statistics: dict[str, MetricStatistics],
        data_quality: DataQuality,
        window: AnalysisWindow,
        expected_interval_seconds: float = 1.0,
    ) -> list[Finding]:
        confidence = self._data_confidence(data_quality)
        findings: list[Finding] = []
        for stat in statistics.values():
            findings.extend(self._metric_rules(stat, confidence))
            findings.extend(self._rapid_rise_rules(stat, confidence, window))
        findings.extend(
            self._data_quality_rules(data_quality, confidence, expected_interval_seconds)
        )
        findings.sort(key=lambda f: (f.rule_id, f.severity))
        return findings

    def _metric_rules(self, stat: MetricStatistics, confidence: float) -> list[Finding]:
        t = self._t
        findings: list[Finding] = []
        c = confidence

        if stat.metric == "coolant_temperature" and stat.maximum is not None:
            if stat.maximum > t.coolant_max_critical:
                findings.append(
                    self._finding(
                        "COOLANT_TEMP_HIGH",
                        "critical",
                        "temperature",
                        stat,
                        stat.maximum,
                        t.coolant_max_critical,
                        c,
                        "Coolant temperature is significantly elevated relative to the configured threshold.",
                    )
                )
            elif stat.maximum > t.coolant_max_warning:
                findings.append(
                    self._finding(
                        "COOLANT_TEMP_HIGH",
                        "warning",
                        "temperature",
                        stat,
                        stat.maximum,
                        t.coolant_max_warning,
                        c,
                        "Coolant temperature is elevated relative to the configured threshold.",
                    )
                )

        if stat.metric == "oil_temperature" and stat.maximum is not None:
            if stat.maximum > t.oil_max_critical:
                findings.append(
                    self._finding(
                        "OIL_TEMP_HIGH",
                        "critical",
                        "temperature",
                        stat,
                        stat.maximum,
                        t.oil_max_critical,
                        c,
                        "Oil temperature is significantly elevated relative to the configured threshold.",
                    )
                )
            elif stat.maximum > t.oil_max_warning:
                findings.append(
                    self._finding(
                        "OIL_TEMP_HIGH",
                        "warning",
                        "temperature",
                        stat,
                        stat.maximum,
                        t.oil_max_warning,
                        c,
                        "Oil temperature is elevated relative to the configured threshold.",
                    )
                )

        if stat.metric == "battery_voltage":
            if stat.minimum is not None and stat.minimum < t.battery_min_critical:
                findings.append(
                    self._finding(
                        "BATTERY_VOLTAGE_LOW",
                        "critical",
                        "electrical",
                        stat,
                        stat.minimum,
                        t.battery_min_critical,
                        c,
                        "Battery voltage is significantly below the configured threshold.",
                    )
                )
            elif stat.minimum is not None and stat.minimum < t.battery_min_warning:
                findings.append(
                    self._finding(
                        "BATTERY_VOLTAGE_LOW",
                        "warning",
                        "electrical",
                        stat,
                        stat.minimum,
                        t.battery_min_warning,
                        c,
                        "Battery voltage is below the configured threshold.",
                    )
                )
            if stat.maximum is not None and stat.maximum > t.battery_max_warning:
                findings.append(
                    self._finding(
                        "BATTERY_VOLTAGE_HIGH",
                        "warning",
                        "electrical",
                        stat,
                        stat.maximum,
                        t.battery_max_warning,
                        c,
                        "Battery voltage is above the configured threshold.",
                    )
                )

        if stat.metric == "engine_load" and stat.mean is not None:
            if stat.mean > t.engine_load_mean_critical:
                findings.append(
                    self._finding(
                        "ENGINE_LOAD_HIGH",
                        "critical",
                        "engine",
                        stat,
                        stat.mean,
                        t.engine_load_mean_critical,
                        c,
                        "Engine load is significantly elevated relative to the configured threshold.",
                    )
                )
            elif stat.mean > t.engine_load_mean_warning:
                findings.append(
                    self._finding(
                        "ENGINE_LOAD_HIGH",
                        "warning",
                        "engine",
                        stat,
                        stat.mean,
                        t.engine_load_mean_warning,
                        c,
                        "Engine load is elevated relative to the configured threshold.",
                    )
                )

        if stat.metric == "rpm" and stat.mean is not None and stat.mean > t.rpm_mean_warning:
            findings.append(
                self._finding(
                    "RPM_UNUSUAL",
                    "warning",
                    "engine",
                    stat,
                    stat.mean,
                    t.rpm_mean_warning,
                    c,
                    "Sustained engine speed is above the configured threshold.",
                )
            )

        if stat.metric == "fuel_level":
            if stat.minimum is not None and stat.minimum < t.fuel_min_critical:
                findings.append(
                    self._finding(
                        "FUEL_LEVEL_LOW",
                        "critical",
                        "fuel",
                        stat,
                        stat.minimum,
                        t.fuel_min_critical,
                        c,
                        "Fuel level is significantly below the configured threshold.",
                    )
                )
            elif stat.minimum is not None and stat.minimum < t.fuel_min_warning:
                findings.append(
                    self._finding(
                        "FUEL_LEVEL_LOW",
                        "warning",
                        "fuel",
                        stat,
                        stat.minimum,
                        t.fuel_min_warning,
                        c,
                        "Fuel level is below the configured threshold.",
                    )
                )

        return findings

    def _rapid_rise_rules(
        self, stat: MetricStatistics, confidence: float, window: AnalysisWindow
    ) -> list[Finding]:
        t = self._t
        if stat.first is None or stat.last is None or stat.count < 3:
            return []
        rise = round(stat.last - stat.first, 4)
        findings: list[Finding] = []
        if stat.metric == "coolant_temperature" and rise >= t.rapid_temp_rise_celsius:
            findings.append(
                self._finding(
                    "RAPID_COOLANT_RISE",
                    "warning",
                    "temperature",
                    stat,
                    rise,
                    t.rapid_temp_rise_celsius,
                    confidence,
                    "Coolant temperature has shown a rapid increase over the analysis window.",
                    window=window,
                )
            )
        if stat.metric == "oil_temperature" and rise >= t.rapid_temp_rise_celsius:
            findings.append(
                self._finding(
                    "RAPID_OIL_TEMP_RISE",
                    "warning",
                    "temperature",
                    stat,
                    rise,
                    t.rapid_temp_rise_celsius,
                    confidence,
                    "Oil temperature has shown a rapid increase over the analysis window.",
                    window=window,
                )
            )
        return findings

    def _data_quality_rules(
        self, dq: DataQuality, confidence: float, expected_interval_seconds: float
    ) -> list[Finding]:
        t = self._t
        findings: list[Finding] = []

        gap_threshold = expected_interval_seconds * t.gap_multiplier
        if dq.max_gap_seconds is not None and dq.max_gap_seconds > gap_threshold:
            findings.append(
                self._finding(
                    "TELEMETRY_GAP",
                    "info",
                    "data_quality",
                    None,
                    round(dq.max_gap_seconds, 3),
                    gap_threshold,
                    confidence,
                    "A gap in telemetry coverage was detected within the analysis window.",
                    metric="telemetry",
                    unit="s",
                )
            )

        if dq.coverage_ratio is not None and dq.coverage_ratio < t.coverage_minimum:
            findings.append(
                self._finding(
                    "LOW_DATA_COVERAGE",
                    "info",
                    "data_quality",
                    None,
                    dq.coverage_ratio,
                    t.coverage_minimum,
                    confidence,
                    "Telemetry coverage is below the configured minimum; the assessment is less reliable.",
                    metric="telemetry",
                    unit="ratio",
                )
            )

        return findings

    def _finding(
        self,
        rule_id: str,
        severity: str,
        category: str,
        stat: MetricStatistics | None,
        observed_value: float | None,
        threshold: float | None,
        confidence: float,
        message: str,
        *,
        metric: str | None = None,
        unit: str | None = None,
        window: AnalysisWindow | None = None,
    ) -> Finding:
        evidence: dict = {}
        if stat is not None:
            evidence["sample_count"] = stat.count
            evidence["mean"] = stat.mean
            evidence["median"] = stat.median
            evidence["minimum"] = stat.minimum
            evidence["maximum"] = stat.maximum
        return Finding(
            rule_id=rule_id,
            severity=severity,
            category=category,
            metric=metric or (stat.metric if stat else None),
            observed_value=observed_value,
            threshold=threshold,
            unit=unit or (stat.unit if stat else None),
            message=message,
            confidence=confidence,
            evidence=evidence,
            window_start=window.start if window else None,
            window_end=window.end if window else None,
        )

    @staticmethod
    def _data_confidence(dq: DataQuality) -> float:
        coverage = dq.coverage_ratio or 0.0
        return round(min(0.95, 0.5 + 0.5 * coverage), 2)

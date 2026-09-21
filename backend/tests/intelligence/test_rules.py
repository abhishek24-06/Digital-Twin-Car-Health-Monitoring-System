from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.intelligence.models import (
    AnalysisWindow,
    DataQuality,
    MetricStatistics,
)
from app.intelligence.rules import HealthRuleEngine, RuleThresholds


def _stat(
    metric: str,
    *,
    minimum: float = 0.0,
    maximum: float = 0.0,
    mean: float = 0.0,
    first: float = 0.0,
    last: float = 0.0,
    count: int = 10,
) -> MetricStatistics:
    return MetricStatistics(
        metric=metric,
        unit="",
        count=count,
        minimum=minimum,
        maximum=maximum,
        mean=mean,
        first=first,
        last=last,
    )


def _window() -> AnalysisWindow:
    end = datetime.now(UTC)
    return AnalysisWindow(start=end - timedelta(minutes=1), end=end, window_minutes=1.0)


def _dq(
    *,
    sample_count: int = 60,
    coverage_ratio: float = 1.0,
    max_gap_seconds: float = 1.0,
) -> DataQuality:
    return DataQuality(
        sample_count=sample_count,
        expected_sample_count=60,
        coverage_ratio=coverage_ratio,
        max_gap_seconds=max_gap_seconds,
    )


def _evaluate(statistics: dict, dq: DataQuality | None = None) -> list:
    engine = HealthRuleEngine()
    return engine.evaluate(
        statistics=statistics,
        data_quality=dq or _dq(),
        window=_window(),
        expected_interval_seconds=1.0,
    )


def _severity(rule_id: str, findings: list) -> str | None:
    for finding in findings:
        if finding.rule_id == rule_id:
            return finding.severity
    return None


def test_healthy_window_has_no_findings() -> None:
    findings = _evaluate(
        {
            "coolant_temperature": _stat(
                "coolant_temperature", maximum=90.0, minimum=88.0, mean=89.0
            ),
            "battery_voltage": _stat("battery_voltage", maximum=13.5, minimum=13.0, mean=13.2),
            "engine_load": _stat("engine_load", minimum=25.0, maximum=30.0, mean=28.0),
            "fuel_level": _stat("fuel_level", minimum=60.0, maximum=61.0, mean=60.5),
        }
    )
    assert findings == []


def test_coolant_critical_on_significant_maximum() -> None:
    stats = {"coolant_temperature": _stat("coolant_temperature", maximum=115.0, mean=112.0)}
    findings = _evaluate(stats)
    assert _severity("COOLANT_TEMP_HIGH", findings) == "critical"


def test_coolant_warning_below_critical_threshold() -> None:
    stats = {"coolant_temperature": _stat("coolant_temperature", maximum=105.0, mean=103.0)}
    findings = _evaluate(stats)
    assert _severity("COOLANT_TEMP_HIGH", findings) == "warning"


def test_oil_critical_on_significant_maximum() -> None:
    stats = {"oil_temperature": _stat("oil_temperature", maximum=115.0, mean=112.0)}
    findings = _evaluate(stats)
    assert _severity("OIL_TEMP_HIGH", findings) == "critical"


def test_battery_voltage_low_warning() -> None:
    stats = {"battery_voltage": _stat("battery_voltage", minimum=11.5, mean=11.7)}
    findings = _evaluate(stats)
    assert _severity("BATTERY_VOLTAGE_LOW", findings) == "warning"


def test_battery_voltage_low_critical() -> None:
    stats = {"battery_voltage": _stat("battery_voltage", minimum=10.0, mean=10.5)}
    findings = _evaluate(stats)
    assert _severity("BATTERY_VOLTAGE_LOW", findings) == "critical"


def test_battery_voltage_high_warning() -> None:
    stats = {"battery_voltage": _stat("battery_voltage", maximum=15.5, mean=15.2)}
    findings = _evaluate(stats)
    assert _severity("BATTERY_VOLTAGE_HIGH", findings) == "warning"


def test_engine_load_warning_on_mean() -> None:
    stats = {"engine_load": _stat("engine_load", mean=42.0, minimum=10.0, maximum=90.0)}
    findings = _evaluate(stats)
    assert _severity("ENGINE_LOAD_HIGH", findings) == "warning"


def test_engine_load_critical_on_mean() -> None:
    stats = {"engine_load": _stat("engine_load", mean=65.0, minimum=10.0, maximum=99.0)}
    findings = _evaluate(stats)
    assert _severity("ENGINE_LOAD_HIGH", findings) == "critical"


def test_rpm_unusual_warning_on_mean() -> None:
    stats = {"rpm": _stat("rpm", mean=4800.0, minimum=4000.0, maximum=5200.0)}
    findings = _evaluate(stats)
    assert _severity("RPM_UNUSUAL", findings) == "warning"


def test_fuel_level_low_warning() -> None:
    stats = {"fuel_level": _stat("fuel_level", minimum=10.0, mean=12.0)}
    findings = _evaluate(stats)
    assert _severity("FUEL_LEVEL_LOW", findings) == "warning"


def test_fuel_level_low_critical() -> None:
    stats = {"fuel_level": _stat("fuel_level", minimum=4.0, mean=5.0)}
    findings = _evaluate(stats)
    assert _severity("FUEL_LEVEL_LOW", findings) == "critical"


def test_rapid_coolant_rise_warning() -> None:
    stats = {
        "coolant_temperature": _stat(
            "coolant_temperature", first=85.0, last=96.0, maximum=96.0, count=30
        )
    }
    findings = _evaluate(stats)
    assert _severity("RAPID_COOLANT_RISE", findings) == "warning"


def test_rapid_oil_temperature_rise_warning() -> None:
    stats = {
        "oil_temperature": _stat("oil_temperature", first=80.0, last=96.0, maximum=96.0, count=30)
    }
    findings = _evaluate(stats)
    assert _severity("RAPID_OIL_TEMP_RISE", findings) == "warning"


def test_no_rapid_rise_below_threshold() -> None:
    stats = {
        "coolant_temperature": _stat(
            "coolant_temperature", first=85.0, last=89.0, maximum=89.0, count=30
        )
    }
    findings = _evaluate(stats)
    assert _severity("RAPID_COOLANT_RISE", findings) is None


def test_telemetry_gap_info_finding() -> None:
    dq = _dq(sample_count=10, coverage_ratio=0.2, max_gap_seconds=30.0)
    findings = _evaluate({}, dq)
    assert _severity("TELEMETRY_GAP", findings) == "info"


def test_low_coverage_info_finding() -> None:
    dq = _dq(sample_count=5, coverage_ratio=0.08, max_gap_seconds=1.0)
    findings = _evaluate({}, dq)
    assert _severity("LOW_DATA_COVERAGE", findings) == "info"


def test_findings_sorted_by_rule_id() -> None:
    stats = {
        "battery_voltage": _stat("battery_voltage", minimum=11.0, mean=11.4),
        "coolant_temperature": _stat("coolant_temperature", maximum=115.0, mean=110.0),
    }
    dq = _dq(sample_count=10, coverage_ratio=0.1, max_gap_seconds=20.0)
    findings = _evaluate(stats, dq)
    rule_ids = [f.rule_id for f in findings]
    assert rule_ids == sorted(rule_ids)


def test_custom_thresholds_are_honoured() -> None:
    engine = HealthRuleEngine(RuleThresholds(coolant_max_warning=120.0, coolant_max_critical=140.0))
    stats = {"coolant_temperature": _stat("coolant_temperature", maximum=125.0, mean=123.0)}
    findings = engine.evaluate(
        statistics=stats,
        data_quality=_dq(),
        window=_window(),
        expected_interval_seconds=1.0,
    )
    assert _severity("COOLANT_TEMP_HIGH", findings) == "warning"

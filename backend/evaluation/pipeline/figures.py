"""Dependency-free SVG figures rendered strictly from ``metrics.json``.

The evaluation host ships no plotting library, and the task forbids adding
dependencies or modifying the shipped analyzer. These figures therefore render
the already-serialized pipeline metrics into small, self-contained SVGs. They
compute no measurement of their own: every value is read from ``metrics.json``,
so a figure can never disagree with the report or the JSON it describes.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from html import escape
from pathlib import Path
from typing import Any

_FONT = "font-family='Segoe UI, Helvetica, Arial, sans-serif'"
#: Fixed palette (colour-blind-friendly-ish, deterministic).
_COLORS = ("#2b6cb0", "#c53030", "#38a169", "#b7791f", "#6b46c1", "#2c7a7b")
_MUTED = "#a0aec0"

_PLOT_LEFT = 72
_PLOT_RIGHT = 24
_PLOT_TOP = 54
_PLOT_HEIGHT = 300
_PLOT_BOTTOM = 104


def _fmt(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def _nice_max(value: float) -> float:
    """Round a maximum up to a readable axis bound (1/2/2.5/5 x 10**k)."""
    if value <= 0:
        return 1.0
    magnitude = 10.0 ** (len(str(int(value))) - 1)
    for factor in (1.0, 2.0, 2.5, 5.0, 10.0):
        candidate = factor * magnitude
        if candidate >= value:
            return float(candidate)
    return float(10 * magnitude)


def _text(
    x: float,
    y: float,
    content: str,
    *,
    size: int = 12,
    anchor: str = "start",
    weight: str = "normal",
    fill: str = "#1a202c",
    rotate: float | None = None,
) -> str:
    transform = f" transform='rotate({rotate} {x:.1f} {y:.1f})'" if rotate else ""
    return (
        f"<text x='{x:.1f}' y='{y:.1f}' {_FONT} font-size='{size}' "
        f"font-weight='{weight}' fill='{fill}' text-anchor='{anchor}'{transform}>"
        f"{escape(str(content))}</text>"
    )


def _svg(width: int, height: int, parts: Iterable[str]) -> str:
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}'>"
        f"<rect width='{width}' height='{height}' fill='white'/>" + "".join(parts) + "</svg>"
    )


def _gridlines(plot_left: int, plot_right: int, vmax: float, *, y_label: str) -> list[str]:
    parts: list[str] = []
    for step in range(5):
        frac = step / 4
        y = _PLOT_TOP + _PLOT_HEIGHT - frac * _PLOT_HEIGHT
        parts.append(
            f"<line x1='{plot_left}' y1='{y:.1f}' x2='{plot_right}' y2='{y:.1f}' "
            "stroke='#e2e8f0' stroke-width='1'/>"
        )
        parts.append(_text(plot_left - 8, y + 4, _fmt(vmax * frac), size=11, anchor="end", fill="#4a5568"))
    parts.append(
        _text(18, _PLOT_TOP + _PLOT_HEIGHT / 2, y_label, size=11, anchor="middle", fill="#4a5568")
    )
    return parts


def _bar_chart(
    title: str,
    y_label: str,
    groups: Sequence[str],
    series: Sequence[tuple[str, str, Sequence[float | None]]],
    *,
    stacked: bool,
) -> str:
    count = len(groups)
    group_w = max(48, 560 // max(1, count))
    plot_right = _PLOT_LEFT + count * group_w
    width = plot_right + _PLOT_RIGHT
    height = _PLOT_TOP + _PLOT_HEIGHT + _PLOT_BOTTOM
    vmax = _nice_max(
        max((v for _, _, vals in series for v in vals if v is not None), default=0.0)
    )
    parts = [_text(_PLOT_LEFT, 28, title, size=17, weight="600")]
    parts += _gridlines(_PLOT_LEFT, plot_right, vmax, y_label=y_label)

    base = _PLOT_TOP + _PLOT_HEIGHT
    for index, group in enumerate(groups):
        group_x = _PLOT_LEFT + index * group_w
        if stacked:
            bar_w = group_w - 16
            top = base
            for _, color, vals in series:
                value = vals[index] or 0.0
                if value <= 0:
                    continue
                h = (value / vmax) * _PLOT_HEIGHT
                parts.append(
                    f"<rect x='{group_x + 8:.1f}' y='{top - h:.1f}' width='{bar_w:.1f}' "
                    f"height='{h:.1f}' fill='{color}'/>"
                )
                top -= h
        else:
            bar_w = (group_w - 12) / len(series)
            for slot, (_, color, vals) in enumerate(series):
                value = vals[index] or 0.0
                h = (value / vmax) * _PLOT_HEIGHT
                parts.append(
                    f"<rect x='{group_x + 6 + slot * bar_w:.1f}' y='{base - h:.1f}' "
                    f"width='{max(1.0, bar_w - 2):.1f}' height='{h:.1f}' fill='{color}'/>"
                )
        parts.append(
            _text(
                group_x + group_w / 2,
                base + 16,
                group,
                size=10,
                anchor="end",
                rotate=-40,
                fill="#2d3748",
            )
        )
    parts.append(
        f"<line x1='{_PLOT_LEFT}' y1='{base}' x2='{plot_right}' y2='{base}' stroke='#4a5568'/>"
    )

    legend_x = _PLOT_LEFT
    legend_y = height - 40
    for name, color, _ in series:
        parts.append(f"<rect x='{legend_x}' y='{legend_y - 10}' width='12' height='12' fill='{color}'/>")
        parts.append(_text(legend_x + 18, legend_y, name, size=11, fill="#2d3748"))
        legend_x += 20 + 7 * len(name) + 22
    return _svg(width, height, parts)


def _scatter(title: str, y_label: str, values: Sequence[float], markers: Sequence[tuple[str, float | None]]) -> str:
    plot_right = _PLOT_LEFT + 640
    width = plot_right + _PLOT_RIGHT
    height = _PLOT_TOP + _PLOT_HEIGHT + 72
    vmax = _nice_max(max(values) if values else 0.0)
    n = len(values)
    parts = [_text(_PLOT_LEFT, 28, title, size=17, weight="600")]
    parts += _gridlines(_PLOT_LEFT, plot_right, vmax, y_label=y_label)

    def x_at(index: int) -> float:
        return _PLOT_LEFT + (index / max(1, n - 1)) * (plot_right - _PLOT_LEFT)

    def y_at(value: float) -> float:
        return _PLOT_TOP + _PLOT_HEIGHT - (value / vmax) * _PLOT_HEIGHT

    for name, marker in markers:
        if marker is None:
            continue
        y = y_at(marker)
        parts.append(
            f"<line x1='{_PLOT_LEFT}' y1='{y:.1f}' x2='{plot_right}' y2='{y:.1f}' "
            "stroke='#c53030' stroke-width='1' stroke-dasharray='5 4'/>"
        )
        parts.append(_text(plot_right - 4, y - 4, f"{name}={_fmt(marker)}", size=10, anchor="end", fill="#c53030"))
    for index, value in enumerate(values):
        parts.append(
            f"<circle cx='{x_at(index):.1f}' cy='{y_at(value):.1f}' r='2.2' fill='{_COLORS[0]}'/>"
        )
    base = _PLOT_TOP + _PLOT_HEIGHT
    parts.append(f"<line x1='{_PLOT_LEFT}' y1='{base}' x2='{plot_right}' y2='{base}' stroke='#4a5568'/>")
    for index in range(0, n, max(1, n // 8)):
        parts.append(_text(x_at(index), base + 18, index, size=10, anchor="middle", fill="#4a5568"))
    parts.append(_text((_PLOT_LEFT + plot_right) / 2, base + 44, "sample index", size=11, anchor="middle", fill="#4a5568"))
    return _svg(width, height, parts)


def render_figures(metrics: dict[str, Any]) -> dict[str, str]:
    """Map ``filename -> svg`` for the sections present in ``metrics``."""
    figures: dict[str, str] = {}

    alerts = metrics.get("alerts") or {}
    per_episode = (alerts.get("summary") or {}).get("per_episode") or []
    if per_episode:
        groups = [row["episode_id"] for row in per_episode]
        matching = [len(row.get("matching_alerts") or []) for row in per_episode]
        false_positive = [len(row.get("false_positive_alerts") or []) for row in per_episode]
        figures["alert-quality.svg"] = _bar_chart(
            "RQ3 alert outcomes per episode",
            "alerts",
            groups,
            [
                ("matching", _COLORS[0], matching),
                ("false positive", _COLORS[1], false_positive),
            ],
            stacked=True,
        )

    recovery = (alerts.get("recovery") or {}).get("cases") or []
    if recovery:
        figures["recovery-ttr.svg"] = _bar_chart(
            "RQ3 time to resolution (fault rule cleared)",
            "seconds",
            [case["scenario"] for case in recovery],
            [("TTR", _COLORS[2], [case.get("ttr_seconds") for case in recovery])],
            stacked=False,
        )

    latency = metrics.get("latency") or {}
    samples = latency.get("samples") or []
    if samples:
        monitor = [s.get("monitor_pass_ms") for s in samples if s.get("monitor_pass_ms") is not None]
        stats = latency.get("monitor_pass_ms") or {}
        if monitor:
            figures["latency-monitor-pass.svg"] = _scatter(
                "RQ4 monitor pass (analyse + alert sync)",
                "ms",
                monitor,
                [("p50", stats.get("p50")), ("p95", stats.get("p95"))],
            )

    cases = (metrics.get("robustness") or {}).get("cases") or []
    if cases:
        figures["robustness-persisted.svg"] = _bar_chart(
            "RQ6 persisted rows vs expected minimum",
            "rows",
            [case["case"] for case in cases],
            [
                ("persisted", _COLORS[0], [case.get("persisted") for case in cases]),
                (
                    "expected min",
                    _MUTED,
                    [(case.get("expected_range") or [None])[0] for case in cases],
                ),
            ],
            stacked=False,
        )
    return figures


def write_figures(metrics: dict[str, Any], out_dir: Path) -> list[Path]:
    """Write ``figures/*.svg`` for a result directory; returns the paths written."""
    figures = render_figures(metrics)
    if not figures:
        return []
    figure_dir = out_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, svg in figures.items():
        target = figure_dir / name
        target.write_text(svg, encoding="utf-8")
        written.append(target)
    return written


__all__ = ["render_figures", "write_figures"]

"""Figures for the exploratory data analysis (matplotlib + seaborn, PNG).

Every figure is drawn from the frames/summary produced by
``evaluation.eda.analysis``. Figures only *describe* the artefacts and compute no
scored metric. EDA is post-hoc, so it sits outside the frozen pre-registration and
never rewrites a scored result.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

#: Channels shown as distribution panels (excludes near-constant channels).
DIST_FEATURES: tuple[str, ...] = (
    "coolant_temperature",
    "oil_temperature",
    "battery_voltage",
    "engine_load",
    "rpm",
    "speed",
    "throttle_position",
    "intake_air_temperature",
)


def _save(fig, path: Path) -> str:
    fig.tight_layout()
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return path.name


def feature_separability(summary: dict, path: Path) -> str:
    eta: dict[str, float] = summary["telemetry"]["eta_squared"]
    ordered = sorted(eta, key=lambda key: eta[key])
    values = [float(eta[key]) for key in ordered]

    fig, ax = plt.subplots(figsize=(9, 5))
    positions = list(range(len(ordered)))
    ax.barh(positions, values, color="#2b6cb0")
    ax.set_yticks(positions)
    ax.set_yticklabels(ordered, fontsize=9)
    ax.set_xlabel("eta-squared (variance explained by scenario)")
    ax.set_xlim(0, 1.05)
    ax.set_title("Telemetry channels ranked by scenario separability")
    for position, value in zip(positions, values, strict=False):
        ax.text(min(value + 0.01, 1.0), position, f"{value:.3f}", va="center", fontsize=8)
    return _save(fig, path)


def scenario_profile_heatmap(summary: dict, path: Path) -> str:
    means = summary["telemetry"]["by_scenario_means"]
    features = list(summary["telemetry"]["features"])
    scenarios = sorted(means)

    raw = np.array([[float(means[scenario][feature]) for feature in features] for scenario in scenarios])
    feature_mean = raw.mean(axis=0)
    feature_std = raw.std(axis=0)
    safe_std = np.where(feature_std > 0, feature_std, 1.0)
    z = (raw - feature_mean) / safe_std
    z[:, feature_std <= 0] = 0.0

    fig, ax = plt.subplots(figsize=(12, 3.4))
    sns.heatmap(
        z,
        ax=ax,
        cmap="coolwarm",
        center=0.0,
        vmin=-3,
        vmax=3,
        xticklabels=features,
        yticklabels=scenarios,
        annot=True,
        fmt=".1f",
        annot_kws={"fontsize": 7},
        cbar_kws={"label": "z-score"},
    )
    ax.set_title("Scenario profile: standardised mean of each channel (z across the four scenarios)")
    ax.set_xticklabels(features, rotation=35, ha="right", fontsize=8)
    fig.tight_layout()
    return _save(fig, path)


def correlation_heatmap(summary: dict, path: Path) -> str:
    labels = summary["telemetry"]["correlation"]["labels"]
    matrix = np.array(summary["telemetry"]["correlation"]["matrix"], dtype=float)
    fig, ax = plt.subplots(figsize=(9, 7.5))
    sns.heatmap(
        matrix,
        ax=ax,
        cmap="coolwarm",
        center=0.0,
        vmin=-1,
        vmax=1,
        xticklabels=labels,
        yticklabels=labels,
        annot=True,
        fmt=".2f",
        annot_kws={"fontsize": 6},
        cbar_kws={"label": "Pearson r"},
    )
    ax.set_title("Pearson correlation between telemetry channels (all points)")
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
    fig.tight_layout()
    return _save(fig, path)


def warmup_trajectories(summary: dict, path: Path) -> str:
    warm = summary["telemetry"]["warmup"]
    times = warm["t"]
    channels = ["coolant_temperature", "oil_temperature"]
    scenarios = sorted(warm["series"]["coolant_temperature"])
    colors = sns.color_palette("deep", len(scenarios))

    fig, axes = plt.subplots(1, 2, figsize=(12, 4), sharex=True)
    for ax, channel in zip(axes, channels, strict=False):
        for scenario, color in zip(scenarios, colors, strict=False):
            ax.plot(
                times,
                warm["series"][channel][scenario],
                label=scenario,
                color=color,
                linewidth=1.8,
            )
        ax.set_title(channel.replace("_", " "))
        ax.set_xlabel("elapsed seconds")
        ax.set_ylabel("deg C")
    axes[0].legend(title="scenario", fontsize=8, loc="lower right")
    fig.suptitle("Cold-start warm-up ramp (mean across episodes)")
    fig.tight_layout()
    return _save(fig, path)


def feature_distributions(telemetry: pd.DataFrame, path: Path) -> str:
    features = [feature for feature in DIST_FEATURES if feature in telemetry]
    ncols = 4
    nrows = int(np.ceil(len(features) / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(4 * ncols, 3 * nrows))
    axes = np.atleast_1d(axes).ravel()
    for ax, feature in zip(axes, features, strict=False):
        sns.violinplot(
            data=telemetry,
            x="scenario",
            y=feature,
            ax=ax,
            inner="quartile",
            cut=0,
            palette="deep",
            hue="scenario",
            legend=False,
        )
        ax.set_title(feature, fontsize=10)
        ax.set_xlabel("")
        ax.tick_params(axis="x", rotation=30, labelsize=7)
        for label in ax.get_xticklabels():
            label.set_horizontalalignment("right")
    for ax in axes[len(features) :]:
        ax.axis("off")
    fig.suptitle("Per-scenario telemetry distributions (violin, quartiles inside)")
    fig.tight_layout()
    return _save(fig, path)


def health_scores(episodes: pd.DataFrame, path: Path) -> str:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), sharey=True)
    order = ["none", "thermal", "electrical", "engine_load"]
    for ax, view in zip(axes, ["steady", "full"], strict=False):
        subset = episodes[episodes["view"] == view]
        sns.stripplot(
            data=subset,
            x="reference_family",
            y="health_score",
            order=order,
            ax=ax,
            hue="health_status",
            dodge=False,
            size=9,
            jitter=0.15,
        )
        ax.set_title(f"{view} view")
        ax.set_xlabel("reference family")
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(title="status", fontsize=8)
    axes[0].set_ylabel("health_score")
    fig.suptitle("Health score by injected family and analysis view (points; colour = status)")
    fig.tight_layout()
    return _save(fig, path)


def rq1_confusion(summary: dict, path: Path) -> str:
    rq1 = summary["rq1_detection"]
    views = [view for view in ("steady", "full") if view in rq1]
    if not views:
        views = sorted(rq1)
    fig, axes = plt.subplots(1, len(views), figsize=(6 * len(views), 5))
    axes = np.atleast_1d(axes)
    for ax, view in zip(axes, views, strict=False):
        confusion = rq1[view]["confusion"]
        labels = rq1[view]["labels"]
        matrix = np.array([[confusion[row][col] for col in labels] for row in labels], dtype=float)
        sns.heatmap(
            matrix,
            ax=ax,
            cmap="Blues",
            annot=True,
            fmt=".0f",
            cbar=False,
            xticklabels=labels,
            yticklabels=labels,
        )
        ax.set_title(
            f"{view}  (acc={rq1[view]['accuracy']}, macro-F1={rq1[view]['macro_f1']})",
            fontsize=10,
        )
        ax.set_xlabel("predicted family")
        ax.set_ylabel("reference family")
        ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
        ax.set_yticklabels(labels, rotation=0, fontsize=8)
    fig.suptitle("RQ1 detection confusion by analysis view")
    fig.tight_layout()
    return _save(fig, path)


def findings_frequency(summary: dict, path: Path) -> str:
    findings = summary["findings_by_view"]
    rows = []
    for view, counts in findings.items():
        for rule, count in counts.items():
            rows.append({"view": view, "rule": rule, "count": count})
    frame = pd.DataFrame(rows)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    if frame.empty:
        ax.axis("off")
    else:
        sns.barplot(data=frame, x="rule", y="count", hue="view", ax=ax, palette="deep")
        ax.set_title("Findings (rule id) emitted per analysis view, summed over episodes")
        ax.set_xlabel("")
        ax.set_ylabel("episodes emitting the finding")
        ax.tick_params(axis="x", rotation=35, labelsize=8)
        for label in ax.get_xticklabels():
            label.set_horizontalalignment("right")
        ax.legend(title="view", fontsize=8)
    fig.tight_layout()
    return _save(fig, path)


def latency_distributions(latency: pd.DataFrame, alert_latency: pd.DataFrame, path: Path) -> str:
    stages = [
        ("ingest_ms", latency),
        ("engine_analysis_duration_ms", latency),
        ("monitor_pass_ms", latency),
        ("publish_to_alert_ms", alert_latency),
    ]
    stages = [(name, frame) for name, frame in stages if name in frame.columns and not frame.empty]
    fig, axes = plt.subplots(1, len(stages), figsize=(4 * len(stages), 4.5))
    axes = np.atleast_1d(axes)
    for ax, (name, frame) in zip(axes, stages, strict=False):
        values = frame[name].dropna().astype(float)
        sns.boxplot(y=values, ax=ax, color="#2b6cb0", width=0.35)
        sns.stripplot(y=values, ax=ax, color="#1a202c", size=3, jitter=0.2)
        ax.set_title(f"{name}\nn={values.size}", fontsize=9)
        ax.set_ylabel("milliseconds (log)")
        ax.set_yscale("log")
    fig.suptitle("Pipeline latency distributions (RQ4, wall-clock)")
    fig.tight_layout()
    return _save(fig, path)


def alert_outcomes(alerts: pd.DataFrame, path: Path) -> str:
    frame = alerts.copy()
    frame["label"] = frame["episode_id"]
    fig, ax = plt.subplots(figsize=(11, 4.5))
    index = np.arange(len(frame))
    ax.bar(index, frame["n_matching"], label="matching", color="#2f855a")
    ax.bar(index, frame["n_false_positive"], bottom=frame["n_matching"], label="false positive", color="#c53030")
    ax.set_xticks(index)
    ax.set_xticklabels(frame["label"], rotation=40, ha="right", fontsize=7)
    ax.set_ylabel("distinct rule ids in episode")
    ax.set_title("RQ3 per-episode alert outcome: expected-rule hits vs false positives")
    ax.legend()
    fig.tight_layout()
    return _save(fig, path)


def robustness_outcomes(robustness: pd.DataFrame, path: Path) -> str:
    frame = robustness.copy().sort_values("persisted")
    fig, ax = plt.subplots(figsize=(10, 4.5))
    index = np.arange(len(frame))
    ax.barh(index, frame["persisted"], color="#2b6cb0", label="persisted")
    ax.plot(frame["expected_min"], index, "o", color="#c53030", label="expected min")
    ax.set_yticks(index)
    ax.set_yticklabels(frame["case"], fontsize=8)
    ax.set_xlabel("rows persisted")
    ax.set_title("RQ6 robustness: persisted vs expected rows per injected-fault case")
    ax.legend()
    fig.tight_layout()
    return _save(fig, path)


def render_all(frames: dict, summary: dict, figures_dir: Path) -> list[str]:
    """Render every figure; return the list of filenames written."""
    figures_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []

    def add(name: str, function, *args) -> None:
        written.append(function(*args, figures_dir / name))

    add("fig01_feature_separability.png", feature_separability, summary)
    add("fig02_scenario_profile.png", scenario_profile_heatmap, summary)
    add("fig03_correlation.png", correlation_heatmap, summary)
    add("fig04_warmup.png", warmup_trajectories, summary)
    if not frames["telemetry"].empty:
        add("fig05_feature_distributions.png", feature_distributions, frames["telemetry"])
    if not frames["episodes"].empty:
        add("fig06_health_scores.png", health_scores, frames["episodes"])
    add("fig07_rq1_confusion.png", rq1_confusion, summary)
    add("fig08_findings.png", findings_frequency, summary)
    if not frames["latency"].empty:
        add(
            "fig09_latency.png",
            latency_distributions,
            frames["latency"],
            frames["alert_latency"],
        )
    if not frames["alerts"].empty:
        add("fig10_alert_outcomes.png", alert_outcomes, frames["alerts"])
    if not frames["robustness"].empty:
        add("fig11_robustness.png", robustness_outcomes, frames["robustness"])
    return written

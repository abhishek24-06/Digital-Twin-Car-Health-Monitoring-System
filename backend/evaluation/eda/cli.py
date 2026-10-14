"""CLI for the post-hoc exploratory data analysis.

Usage (from ``backend/``)::

    python -m evaluation.eda
    python -m evaluation.eda --out docs/research/results/synthetic-eda-v1 --force

It reads the *frozen* evaluation artefacts read-only and writes a new,
clearly-labelled EDA result set (``eda_metrics.json``, ``EDA.md``, ``figures/``,
``README.md``, ``provenance.json``). It never touches the frozen protocol files or
the scored result sets.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

import matplotlib
import numpy
import pandas
import seaborn

from evaluation.eda import analysis, figures, report

REPO_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_OUT = REPO_ROOT / "docs" / "research" / "results" / "synthetic-eda-v1"
DEFAULT_DATASET = (
    REPO_ROOT / "docs" / "research" / "results" / "synthetic-scenarios-v2" / "dataset.json"
)
DEFAULT_SCENARIOS = (
    REPO_ROOT / "docs" / "research" / "results" / "synthetic-scenarios-v2" / "metrics.json"
)
DEFAULT_PIPELINE = (
    REPO_ROOT / "docs" / "research" / "results" / "synthetic-pipeline-v1" / "metrics.json"
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evaluation.eda",
        description="Post-hoc EDA over the frozen evaluation artefacts.",
    )
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET), help="scenarios dataset.json")
    parser.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS), help="scenarios metrics.json")
    parser.add_argument("--pipeline", default=str(DEFAULT_PIPELINE), help="pipeline metrics.json")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output directory")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing EDA.md in the output directory",
    )
    return parser


def _source_record(path: Path) -> dict:
    return {
        "path": path.resolve().relative_to(REPO_ROOT).as_posix(),
        "sha256": analysis.sha256_file(path),
        "bytes": path.stat().st_size,
    }


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    out_dir = Path(args.out)
    dataset_path = Path(args.dataset)
    scenarios_path = Path(args.scenarios)
    pipeline_path = Path(args.pipeline)

    for name, path in (
        ("dataset", dataset_path),
        ("scenarios", scenarios_path),
        ("pipeline", pipeline_path),
    ):
        if not path.exists():
            print(f"error: {name} input not found: {path}", file=sys.stderr)
            return 2

    if (out_dir / "EDA.md").exists() and not args.force:
        print(
            f"error: {out_dir / 'EDA.md'} exists; pass --force to overwrite",
            file=sys.stderr,
        )
        return 2

    dataset = analysis.load_json(dataset_path)
    scenarios_metrics = analysis.load_json(scenarios_path)
    pipeline_metrics = analysis.load_json(pipeline_path)

    telemetry = analysis.telemetry_frame(dataset)
    episodes = analysis.episodes_frame(scenarios_metrics)
    frames = {
        "telemetry": telemetry,
        "episodes": episodes,
        "alerts": analysis.alerts_frame(pipeline_metrics),
        "latency": analysis.latency_frame(pipeline_metrics),
        "alert_latency": analysis.alert_latency_frame(pipeline_metrics),
        "robustness": analysis.robustness_frame(pipeline_metrics),
    }

    manifest = dataset.get("manifest") or {}
    inputs = {
        "dataset_id": manifest.get("dataset_id"),
        "code_revision": manifest.get("code_revision"),
        "scope": "synthetic-scenarios-v2 (accuracy) + synthetic-pipeline-v1 (pipeline)",
        "generated_at": datetime.now(UTC).isoformat(),
        "n_episodes": int(telemetry["episode_id"].nunique()),
        "points": int(len(telemetry)),
        "features": int(len(analysis.FEATURES)),
        "pipeline_dataset_id": (pipeline_metrics.get("meta") or {}).get("dataset_id"),
        "sources": {
            "synthetic-scenarios-v2/dataset.json": _source_record(dataset_path),
            "synthetic-scenarios-v2/metrics.json": _source_record(scenarios_path),
            "synthetic-pipeline-v1/metrics.json": _source_record(pipeline_path),
        },
    }

    summary = analysis.clean(
        analysis.summarize(telemetry, episodes, scenarios_metrics, pipeline_metrics, inputs)
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = out_dir / "eda_metrics.json"
    metrics_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    reloaded = json.loads(metrics_path.read_text(encoding="utf-8"))
    (out_dir / "EDA.md").write_text(report.render_markdown(reloaded), encoding="utf-8")

    written = figures.render_all(frames, summary, out_dir / "figures")

    (out_dir / "README.md").write_text(_readme(reloaded, written), encoding="utf-8")
    (out_dir / "provenance.json").write_text(
        json.dumps(_provenance(inputs, written), indent=2), encoding="utf-8"
    )

    print(f"EDA artifacts written to {out_dir} ({len(written)} figures)")
    return 0


def _readme(summary: dict, written: list[str]) -> str:
    inputs = summary.get("inputs") or {}
    lines = [
        "# Exploratory Data Analysis — Digital Twin evaluation",
        "",
        f"**Provenance: {summary['meta']['provenance']}.** Post-hoc and exploratory;",
        "**not** the frozen pre-registration, and not a scored result.",
        "",
        "## Artifacts",
        "",
        "| File | Contents |",
        "| --- | --- |",
        "| `eda_metrics.json` | All computed statistics; the single source of truth. |",
        "| `EDA.md` | Human-readable report rendered from `eda_metrics.json`. |",
        "| `figures/*.png` | matplotlib/seaborn figures. |",
        "| `provenance.json` | Input hashes, library versions, commands, limitations. |",
        "",
        "## Reproduce",
        "",
        "From `backend/`:",
        "",
        "```",
        "python -m evaluation.eda --force",
        "```",
        "",
        "## Inputs",
        "",
        f"- Scenarios dataset: `{inputs.get('dataset_id')}` (revision `{inputs.get('code_revision')}`)",
        f"- Pipeline dataset: `{inputs.get('pipeline_dataset_id')}`",
        f"- Episodes: {inputs.get('n_episodes')}; points: {inputs.get('points')}",
        "",
        f"Figures: {', '.join(written) if written else '(none)'}",
        "",
    ]
    return "\n".join(lines) + "\n"


def _provenance(inputs: dict, written: list[str]) -> dict:
    return {
        "analysis": "exploratory data analysis",
        "status": "EXECUTED",
        "provenance": "SIMULATED telemetry + MEASURED pipeline behaviour",
        "generated_at": inputs.get("generated_at"),
        "command": "python -m evaluation.eda --force",
        "inputs": inputs.get("sources"),
        "figures": written,
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "matplotlib": matplotlib.__version__,
            "seaborn": seaborn.__version__,
            "numpy": numpy.__version__,
            "pandas": pandas.__version__,
        },
        "limitations": [
            "Synthetic telemetry from the in-repo simulator; not real-world data.",
            "Reference labels are the injected scenarios, not independent sensor labels.",
            "Descriptive only: no hypothesis test, no p-value, no significance claim.",
            "Post-hoc and outside the frozen pre-registration; never a scored result.",
        ],
    }


__all__ = ["main"]

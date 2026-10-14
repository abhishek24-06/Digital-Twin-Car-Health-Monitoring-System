"""CLI entry point for the evaluation framework.

Usage (from ``backend/``)::

    python -m evaluation generate --seeds 1 2 3 4 5
    python -m evaluation analyze
    python -m evaluation render          # re-render REPORT.md from metrics.json
    python -m evaluation hash            # (re)write PLAN_HASHES.json for a dataset
    python -m evaluation all

Results are written under ``docs/research/results/<dataset_id>/``.

Consistency contract
--------------------
``REPORT.md`` is always rendered **from the bytes of ``metrics.json``**: the
runner writes the JSON, reads it back, and only then renders the Markdown. A
report and its metrics therefore cannot disagree, even across separate runs.
A frozen result directory (one carrying ``PLAN_HASHES.json``) is never
overwritten once the frozen files change; pick a new ``--dataset`` id or pass
``--force`` to override deliberately.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evaluation.analysis import evaluate
from evaluation.hashing import (
    FROZEN_PATHS,
    HASHES_FILENAME,
    build_hashes_payload,
    content_hashes,
    frozen_mismatches,
)
from evaluation.registry import DatasetManifest
from evaluation.report import LIMITATIONS, render_markdown
from evaluation.runner import EpisodeResult, analyze_episode
from evaluation.scenarios import Episode, ScenarioSpec, build_dataset_specs, generate_episode

DEFAULT_DATASET = "synthetic-scenarios-v2"
DEFAULT_SCENARIOS: tuple[str, ...] = (
    "normal",
    "high_temperature",
    "low_battery",
    "high_engine_load",
)
DEFAULT_SEEDS: tuple[int, ...] = (1, 2, 3, 4, 5)
PROVENANCE_TAG = "SIMULATED"
GENERATOR = "backend/simulator/telemetry_generator.SimulationEngine (unmodified)"

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_ROOT = REPO_ROOT / "docs" / "research" / "results"


class FrozenDatasetError(RuntimeError):
    """Raised when a run would overwrite a frozen result set with changed code."""


def _code_revision() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "unknown"
    return result.stdout.strip() or "unknown"


def assert_not_frozen(out_dir: Path, *, force: bool) -> None:
    """Fail closed when a frozen dataset no longer matches the working tree."""
    mismatches = frozen_mismatches(out_dir, REPO_ROOT)
    if not mismatches:
        return
    if force:
        return
    joined = ", ".join(sorted(mismatches))
    raise FrozenDatasetError(
        f"{out_dir.name!r} is frozen and {len(mismatches)} frozen file(s) have changed "
        f"({joined}). A frozen experiment must never be silently rewritten; choose a new "
        "--dataset id (e.g. synthetic-scenarios-v2) or pass --force deliberately."
    )


def write_plan_hashes(dataset_id: str, out_dir: Path) -> Path:
    files = content_hashes(FROZEN_PATHS, root=REPO_ROOT)
    payload = build_hashes_payload(dataset_id, _code_revision(), files)
    target = out_dir / HASHES_FILENAME
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def write_metrics_and_report(out_dir: Path, report: dict[str, Any]) -> None:
    """Persist metrics.json, then render REPORT.md strictly from those bytes."""
    metrics_path = out_dir / "metrics.json"
    metrics_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    reloaded = json.loads(metrics_path.read_text(encoding="utf-8"))
    (out_dir / "REPORT.md").write_text(render_markdown(reloaded), encoding="utf-8")


def render_from_metrics(out_dir: Path) -> Path:
    """Re-render REPORT.md from an existing metrics.json (single source of truth)."""
    metrics_path = out_dir / "metrics.json"
    if not metrics_path.exists():
        raise FileNotFoundError(f"no metrics.json in {out_dir}")
    report = json.loads(metrics_path.read_text(encoding="utf-8"))
    target = out_dir / "REPORT.md"
    target.write_text(render_markdown(report), encoding="utf-8")
    return target


def build_manifest(
    dataset_id: str,
    episodes: list[Episode],
    code_revision: str,
) -> DatasetManifest:
    return DatasetManifest(
        dataset_id=dataset_id,
        generator=GENERATOR,
        description="Deterministic synthetic fault episodes from the in-repo simulator.",
        reference_source="harness-injected-scenario",
        label_method="injected-physical-condition",
        label_version="1.0",
        code_revision=code_revision,
        limitations=list(LIMITATIONS),
        episodes=[episode.provenance for episode in episodes],
    )


def _generate_all(
    dataset_id: str, scenarios: tuple[str, ...], seeds: tuple[int, ...]
) -> tuple[list[ScenarioSpec], list[Episode]]:
    specs = build_dataset_specs(scenarios, seeds)
    episodes = [generate_episode(dataset_id, spec) for spec in specs]
    return specs, episodes


def _analyze_all(specs: list[ScenarioSpec], episodes: list[Episode]) -> list[EpisodeResult]:
    results: list[EpisodeResult] = []
    for spec, episode in zip(specs, episodes, strict=True):
        results.extend(analyze_episode(episode, spec))
    return results


def run(
    dataset_id: str,
    scenarios: tuple[str, ...],
    seeds: tuple[int, ...],
    command: str,
    action: str = "all",
    *,
    force: bool = False,
) -> Path:
    out_dir = RESULTS_ROOT / dataset_id
    out_dir.mkdir(parents=True, exist_ok=True)
    assert_not_frozen(out_dir, force=force)

    if action == "render":
        render_from_metrics(out_dir)
        return out_dir
    if action == "hash":
        write_plan_hashes(dataset_id, out_dir)
        return out_dir

    specs, episodes = _generate_all(dataset_id, scenarios, seeds)
    manifest = build_manifest(dataset_id, episodes, _code_revision())

    if action in ("all", "generate"):
        dataset_doc = {
            "manifest": manifest.model_dump(mode="json"),
            "episodes": [_episode_to_dict(episode) for episode in episodes],
        }
        (out_dir / "dataset.json").write_text(json.dumps(dataset_doc, indent=2), encoding="utf-8")
        (out_dir / "provenance.json").write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2), encoding="utf-8"
        )

    if action in ("all", "analyze"):
        results = _analyze_all(specs, episodes)
        views = evaluate(results)
        report: dict[str, Any] = {
            "dataset_id": dataset_id,
            "generated_at": datetime.now(UTC).isoformat(),
            "provenance_tag": PROVENANCE_TAG,
            "commands": [command],
            "manifest": manifest.model_dump(mode="json"),
            "views": views,
            "episodes": [result.to_dict() for result in results],
        }
        write_metrics_and_report(out_dir, report)
    return out_dir


def _episode_to_dict(episode: Episode) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provenance": episode.provenance.model_dump(mode="json"),
        "points": [
            {"timestamp": point.timestamp.isoformat(), "values": point.values}
            for point in episode.points
        ],
    }
    return payload


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Digital Twin accuracy evaluation framework")
    parser.add_argument(
        "action",
        nargs="?",
        default="all",
        choices=["all", "generate", "analyze", "render", "hash"],
        help="all = generate + analyze + report (default)",
    )
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--scenarios", nargs="+", default=list(DEFAULT_SCENARIOS))
    parser.add_argument("--seeds", nargs="+", type=int, default=list(DEFAULT_SEEDS))
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite a frozen result directory even though its recorded hashes changed",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    command = "python -m evaluation " + " ".join(sys.argv[1:])
    try:
        out_dir = run(
            dataset_id=args.dataset,
            scenarios=tuple(args.scenarios),
            seeds=tuple(args.seeds),
            command=command,
            action=args.action,
            force=args.force,
        )
    except FrozenDatasetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"evaluation artifacts written to {out_dir}")
    return 0


__all__ = ["main", "run", "write_metrics_and_report", "render_from_metrics", "write_plan_hashes"]


if __name__ == "__main__":
    raise SystemExit(main())

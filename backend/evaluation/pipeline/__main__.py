"""CLI entry point for the end-to-end pipeline evaluation (RQ3/RQ4/RQ6).

Usage (from ``backend/``)::

    python -m evaluation.pipeline all
    python -m evaluation.pipeline alerts
    python -m evaluation.pipeline latency
    python -m evaluation.pipeline robustness
    python -m evaluation.pipeline render

It requires a private Mosquitto broker and a dedicated disposable PostgreSQL
database named ``digital_twin_eval_test`` on loopback. The target is supplied via
``DT_EVAL_DATABASE_URL`` (a documented loopback default is used when unset) and
is verified by a **fail-closed** guard: anything not loopback and not exactly that
database name is refused before a single row is touched.

If the broker or database is unavailable, or the guard rejects the target, the
run is reported **NOT EXECUTED** with the blocker recorded — never a fabricated
result. ``REPORT.md`` is always rendered from the bytes of ``metrics.json``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evaluation.hashing import (
    HASHES_FILENAME,
    PIPELINE_FROZEN_PATHS,
    build_hashes_payload,
    content_hashes,
    frozen_mismatches,
)
from evaluation.pipeline import metrics as M
from evaluation.pipeline.experiments import (
    AlertExperimentConfig,
    LatencyConfig,
    run_alert_experiment,
    run_latency_experiment,
    run_recovery_experiment,
    run_robustness_experiment,
)
from evaluation.pipeline.figures import write_figures
from evaluation.pipeline.harness import (
    DEFAULT_DATABASE_URL,
    EVAL_DATABASE_URL_ENV,
    EvaluationDatabase,
    HarnessUnavailable,
    IsolationError,
    Publisher,
    broker_settings,
    ensure_database_exists,
    environment_info,
    find_mosquitto,
    resolve_database_url,
    running_broker,
)
from evaluation.pipeline.report import render_markdown

#: ``backend/evaluation/pipeline/__main__.py`` -> repo root is four levels up.
REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_ROOT = REPO_ROOT / "docs" / "research" / "results"

DEFAULT_RESULT_ID = "synthetic-pipeline-v1"
DEFAULT_ALERT_SCENARIOS: tuple[str, ...] = (
    "normal",
    "high_temperature",
    "low_battery",
    "high_engine_load",
)
DEFAULT_ALERT_SEEDS: tuple[int, ...] = (1, 2, 3)
DEFAULT_RECOVERY_SCENARIOS: tuple[str, ...] = (
    "high_temperature",
    "low_battery",
    "high_engine_load",
)
DEFAULT_LATENCY_SCENARIO = "high_temperature"
DEFAULT_LATENCY_SEEDS: tuple[int, ...] = (1, 2, 3)
DEFAULT_LATENCY_SAMPLES = 60
DEFAULT_ROBUSTNESS_SEED = 7

SECTIONS: tuple[str, ...] = ("alerts", "latency", "robustness")
PROVENANCE = "SIMULATED episodes + MEASURED real-pipeline behaviour"


class FrozenResultError(RuntimeError):
    """Raised when a run would overwrite a frozen pipeline result set."""


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
    mismatches = frozen_mismatches(out_dir, REPO_ROOT)
    if not mismatches or force:
        return
    joined = ", ".join(sorted(mismatches))
    raise FrozenResultError(
        f"{out_dir.name!r} is a frozen pipeline result set and {len(mismatches)} frozen "
        f"file(s) have changed ({joined}). Choose a new --dataset id or pass --force "
        "deliberately."
    )


def _write_plan_hashes(dataset_id: str, out_dir: Path) -> Path:
    files = content_hashes(PIPELINE_FROZEN_PATHS, root=REPO_ROOT)
    payload = build_hashes_payload(dataset_id, _code_revision(), files)
    target = out_dir / HASHES_FILENAME
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def _load_metrics(out_dir: Path) -> dict[str, Any] | None:
    path = out_dir / "metrics.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _render_from_metrics(out_dir: Path) -> Path:
    metrics = _load_metrics(out_dir)
    if metrics is None:
        raise FileNotFoundError(f"no metrics.json in {out_dir}")
    target = out_dir / "REPORT.md"
    target.write_text(render_markdown(metrics), encoding="utf-8")
    return target


def _readme(metrics: dict[str, Any]) -> str:
    """Human-facing README for a result directory (rendered from ``metrics``)."""
    meta = metrics.get("meta") or {}
    lines = [
        f"# Pipeline evaluation — `{meta.get('dataset_id') or DEFAULT_RESULT_ID}`",
        "",
        "**Provenance: `SIMULATED` episodes + `MEASURED` pipeline behaviour.** The",
        "telemetry is produced by the in-repo simulator; the pipeline behaviour it drives "
        "(MQTT ingestion, persistence, the live alert path, latency and fault tolerance) "
        "is measured on the real services. This is **not** real-vehicle validation.",
        "",
        "## Artifacts",
        "",
        "| File | Contents |",
        "| --- | --- |",
        "| `metrics.json` | Serialized measurements; the single source of truth. |",
        "| `REPORT.md` | Human-readable report rendered from the bytes of `metrics.json`. |",
        "| `provenance.json` | Run metadata, environment and per-section configuration. |",
        "| `PLAN_HASHES.json` | sha256 of the frozen protocol and analyzer files. |",
        "| `figures/*.svg` | Dependency-free figures rendered from `metrics.json`. |",
        "",
        "## Reproduce",
        "",
        "From `backend/` (requires a private Mosquitto broker and a dedicated disposable",
        "PostgreSQL database named `digital_twin_eval_test` on loopback):",
        "",
        "```",
        "python -m evaluation.pipeline all",
        "```",
        "",
        "The **fail-closed** isolation guard refuses any non-loopback or differently named",
        "database before a single row is touched. If the broker or database is unavailable",
        "the run is recorded `NOT EXECUTED` with the blocker, never a fabricated result.",
        "",
        "## Commands recorded in this result set",
        "",
    ]
    commands = metrics.get("meta", {}).get("commands") or []
    lines += [f"- `{command}`" for command in commands] or ["- (none recorded)"]
    return "\n".join(lines) + "\n"


def _write_artifacts(out_dir: Path, metrics: dict[str, Any]) -> None:
    metrics_path = out_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    reloaded = json.loads(metrics_path.read_text(encoding="utf-8"))
    (out_dir / "REPORT.md").write_text(render_markdown(reloaded), encoding="utf-8")
    (out_dir / "README.md").write_text(_readme(reloaded), encoding="utf-8")
    write_figures(reloaded, out_dir)
    (out_dir / "provenance.json").write_text(
        json.dumps(
            {
                "meta": metrics.get("meta"),
                "environment": metrics.get("environment"),
                "section_config": {
                    key: metrics.get(key, {}).get("config")
                    for key in ("alerts", "latency", "robustness")
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_plan_hashes(
        str((metrics.get("meta") or {}).get("dataset_id") or DEFAULT_RESULT_ID), out_dir
    )


def _write_not_executed(out_dir: Path, dataset_id: str, command: str, blocker: str) -> None:
    """Record a NOT EXECUTED status without destroying an existing result set."""
    status = {
        "dataset_id": dataset_id,
        "status": "NOT EXECUTED",
        "blocker": blocker,
        "generated_at": datetime.now(UTC).isoformat(),
        "command": command,
    }
    (out_dir / "STATUS.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    if _load_metrics(out_dir) is None:
        metrics = {
            "meta": {
                "dataset_id": dataset_id,
                "generated_at": status["generated_at"],
                "provenance": "NOT EXECUTED",
                "code_revision": _code_revision(),
                "status": "NOT EXECUTED",
                "blocker": blocker,
                "commands": [command],
            }
        }
        _write_artifacts(out_dir, metrics)


# --------------------------------------------------------------------------- #
# Experiment orchestration
# --------------------------------------------------------------------------- #


async def _run_alerts(database, settings, publisher, args) -> dict[str, Any]:
    config = AlertExperimentConfig(
        dataset_id=args.dataset,
        scenarios=tuple(args.alert_scenarios),
        seeds=tuple(args.alert_seeds),
        duration_seconds=args.duration_seconds,
    )
    result = await run_alert_experiment(database, settings, publisher, config)
    summary = M.summarize_alerts(result.episodes)

    recovery_episodes = await run_recovery_experiment(
        database,
        settings,
        publisher,
        dataset_id=args.dataset,
        scenarios=tuple(args.recovery_scenarios),
        seed=args.recovery_seed,
        fault_seconds=args.recovery_fault_seconds,
        clean_seconds=args.recovery_clean_seconds,
    )
    recovery_summary = M.summarize_alerts(recovery_episodes)
    recovery_cases = []
    for episode in recovery_episodes:
        resolved = []
        ttr: float | None = None
        if episode.recovery_onset is not None:
            for alert in episode.alerts:
                if alert.resolved_at is None or alert.rule_id not in episode.expected_rule_ids:
                    continue
                resolved.append(alert.rule_id)
                delta = (alert.resolved_at - episode.recovery_onset).total_seconds()
                ttr = delta if ttr is None else min(ttr, delta)
        recovery_cases.append(
            {
                "scenario": episode.scenario,
                "expected_rule_ids": list(episode.expected_rule_ids),
                "resolved_rule_ids": resolved,
                "ttr_seconds": ttr,
            }
        )

    return {
        "provenance": "SIMULATED episode labels; MEASURED alert materialization",
        "config": {
            "dataset_id": config.dataset_id,
            "scenarios": list(config.scenarios),
            "seeds": list(config.seeds),
            "duration_seconds": config.duration_seconds,
            "recovery_scenarios": list(args.recovery_scenarios),
            "recovery_seed": args.recovery_seed,
        },
        "summary": summary,
        "publish_stats": result.publish_stats,
        "scope_counts": result.scope_counts,
        "episodes": [episode.to_dict() for episode in result.episodes],
        "recovery": {
            "summary": recovery_summary,
            "cases": recovery_cases,
            "episodes": [episode.to_dict() for episode in recovery_episodes],
        },
    }


async def _run_latency(database, settings, publisher, args) -> dict[str, Any]:
    config = LatencyConfig(
        dataset_id=args.dataset,
        scenario=args.latency_scenario,
        seeds=tuple(args.latency_seeds),
        samples=args.latency_samples,
        interval_seconds=args.latency_interval,
    )
    result = await run_latency_experiment(database, settings, publisher, config)
    samples = result["samples"]
    alerts = result["alert_latencies"]
    return {
        "provenance": "MEASURED (real MQTT -> subscriber -> DB -> analyzer -> alert)",
        "config": {
            "dataset_id": config.dataset_id,
            "scenario": config.scenario,
            "seeds": list(config.seeds),
            "samples": config.samples,
            "interval_seconds": config.interval_seconds,
        },
        "n_samples": len(samples),
        "n_alerts": len(alerts),
        "ingest_ms": M.summarize_latency(
            [s["ingest_ms"] for s in samples if s.get("ingest_ms") is not None]
        ),
        "monitor_pass_ms": M.summarize_latency(
            [s["monitor_pass_ms"] for s in samples if s.get("monitor_pass_ms") is not None]
        ),
        "engine_analysis_duration_ms": M.summarize_latency(
            [
                s["engine_analysis_duration_ms"]
                for s in samples
                if s.get("engine_analysis_duration_ms") is not None
            ]
        ),
        "publish_to_alert_ms": M.summarize_latency(
            [a["publish_to_alert_ms"] for a in alerts if a.get("publish_to_alert_ms") is not None]
        ),
        "samples": samples,
        "alert_latencies": alerts,
        "failures": result["failures"],
    }


async def _run_robustness(database, settings, broker, args) -> dict[str, Any]:
    cases = await run_robustness_experiment(
        database, settings, broker, dataset_id=args.dataset, seed=args.robustness_seed
    )
    return {
        "provenance": "MEASURED (injected faults on the real ingestion path)",
        "config": {"dataset_id": args.dataset, "seed": args.robustness_seed},
        "cases": cases,
    }


async def _execute(args, sections: tuple[str, ...]) -> dict[str, Any]:
    url = resolve_database_url(args.database)
    await ensure_database_exists(url)
    database = EvaluationDatabase(url)
    await database.create_schema()
    executable = find_mosquitto()
    executed: dict[str, Any] = {"sections": {}}
    try:
        with running_broker(executable) as broker:
            settings = broker_settings(
                broker,
                batch_max_messages=1,
                batch_flush_seconds=5.0,
                retry_attempts=args.retry_attempts,
            )
            executed["environment"] = environment_info(url, broker, settings)
            if "alerts" in sections or "latency" in sections:
                async with Publisher(settings) as publisher:
                    if "alerts" in sections:
                        executed["sections"]["alerts"] = await _run_alerts(
                            database, settings, publisher, args
                        )
                    if "latency" in sections:
                        executed["sections"]["latency"] = await _run_latency(
                            database, settings, publisher, args
                        )
            if "robustness" in sections:
                executed["sections"]["robustness"] = await _run_robustness(
                    database, settings, broker, args
                )
    finally:
        await database.drop_schema()
        await database.dispose()
    return executed


def _merge(existing: dict[str, Any] | None, executed: dict[str, Any], args, command: str) -> dict:
    metrics = dict(existing or {})
    meta = dict(metrics.get("meta") or {})
    commands = list(meta.get("commands") or [])
    if command not in commands:
        commands.append(command)
    meta.update(
        {
            "dataset_id": args.dataset,
            "generated_at": datetime.now(UTC).isoformat(),
            "provenance": "SIMULATED (episodes) + MEASURED (pipeline behavior)",
            "code_revision": _code_revision(),
            "status": "EXECUTED",
            "commands": commands,
        }
    )
    meta.pop("blocker", None)
    metrics["meta"] = meta
    if executed.get("environment"):
        metrics["environment"] = executed["environment"]
    for key, value in executed.get("sections", {}).items():
        metrics[key] = value
    return metrics


def _run_async(coro):
    if sys.platform == "win32":
        loop = asyncio.SelectorEventLoop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
            asyncio.set_event_loop(None)
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Digital Twin pipeline evaluation (RQ3/RQ4/RQ6)")
    parser.add_argument(
        "action",
        nargs="?",
        default="all",
        choices=["all", "alerts", "latency", "robustness", "render", "figures"],
    )
    parser.add_argument("--dataset", default=DEFAULT_RESULT_ID)
    parser.add_argument("--database", default=None, help="isolated disposable DB URL")
    parser.add_argument("--alert-scenarios", nargs="+", default=list(DEFAULT_ALERT_SCENARIOS))
    parser.add_argument("--alert-seeds", nargs="+", type=int, default=list(DEFAULT_ALERT_SEEDS))
    parser.add_argument("--duration-seconds", type=float, default=180.0)
    parser.add_argument("--recovery-scenarios", nargs="+", default=list(DEFAULT_RECOVERY_SCENARIOS))
    parser.add_argument("--recovery-seed", type=int, default=1)
    parser.add_argument("--recovery-fault-seconds", type=float, default=180.0)
    parser.add_argument("--recovery-clean-seconds", type=float, default=60.0)
    parser.add_argument("--latency-scenario", default=DEFAULT_LATENCY_SCENARIO)
    parser.add_argument("--latency-seeds", nargs="+", type=int, default=list(DEFAULT_LATENCY_SEEDS))
    parser.add_argument("--latency-samples", type=int, default=DEFAULT_LATENCY_SAMPLES)
    parser.add_argument("--latency-interval", type=float, default=1.0)
    parser.add_argument("--robustness-seed", type=int, default=DEFAULT_ROBUSTNESS_SEED)
    parser.add_argument("--retry-attempts", type=int, default=3)
    parser.add_argument(
        "--force", action="store_true", help="overwrite a frozen pipeline result set"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    args = _parse_args(raw)
    out_dir = RESULTS_ROOT / args.dataset
    out_dir.mkdir(parents=True, exist_ok=True)
    command = "python -m evaluation.pipeline " + " ".join(raw)

    if args.action == "render":
        try:
            target = _render_from_metrics(out_dir)
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"re-rendered {target}")
        return 0

    if args.action == "figures":
        metrics = _load_metrics(out_dir)
        if metrics is None:
            print(f"error: no metrics.json in {out_dir}", file=sys.stderr)
            return 2
        written = write_figures(metrics, out_dir)
        print(f"wrote {len(written)} figure(s) to {out_dir / 'figures'}")
        return 0

    try:
        assert_not_frozen(out_dir, force=args.force)
    except FrozenResultError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    os.environ.setdefault(EVAL_DATABASE_URL_ENV, DEFAULT_DATABASE_URL)
    sections = ("alerts", "latency", "robustness") if args.action == "all" else (args.action,)
    try:
        executed = _run_async(_execute(args, sections))
    except (IsolationError, HarnessUnavailable) as exc:
        _write_not_executed(out_dir, args.dataset, command, str(exc))
        print(f"NOT EXECUTED: {exc}", file=sys.stderr)
        return 3

    metrics = _merge(_load_metrics(out_dir), executed, args, command)
    _write_artifacts(out_dir, metrics)
    print(f"pipeline evaluation artifacts written to {out_dir}")
    return 0


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())

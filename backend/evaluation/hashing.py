"""Content hashing for the frozen pre-registration (plan §5, §11).

A result set is only valid against the exact protocol + metric implementation it
was produced with. This module records sha256 content hashes of the frozen files
and lets the runner refuse to overwrite a result directory whose recorded hashes
no longer match the working tree — the mechanical guard against silently
rewriting a frozen experiment with changed code.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

#: Repo-root-relative files that make up the frozen protocol. Changing any of
#: them invalidates an existing result set and requires a new ``dataset_id``.
FROZEN_PATHS: tuple[str, ...] = (
    "docs/research/accuracy_evaluation_plan.md",
    "backend/evaluation/registry.py",
    "backend/evaluation/analysis.py",
    "backend/evaluation/report.py",
    "backend/evaluation/metrics/detection.py",
    "backend/evaluation/metrics/health.py",
    "backend/evaluation/metrics/latency.py",
    "backend/evaluation/metrics/diagnosis.py",
    "backend/evaluation/scenarios.py",
    "backend/evaluation/runner.py",
)

HASHES_FILENAME = "PLAN_HASHES.json"

#: Frozen files for the *pipeline* result set: the analyzer protocol plus the
#: runtime services whose semantics the alerts/latency measurements depend on.
#: A change to any of these invalidates a recorded pipeline result set.
PIPELINE_FROZEN_PATHS: tuple[str, ...] = FROZEN_PATHS + (
    "backend/evaluation/pipeline/__main__.py",
    "backend/evaluation/pipeline/experiments.py",
    "backend/evaluation/pipeline/figures.py",
    "backend/evaluation/pipeline/metrics.py",
    "backend/evaluation/pipeline/harness.py",
    "backend/evaluation/pipeline/report.py",
    "backend/app/services/alert_service.py",
    "backend/app/services/vehicle_health_service.py",
)


def sha256_file(path: Path) -> str:
    """sha256 hex digest of a file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hashes(paths: tuple[str, ...] = FROZEN_PATHS, *, root: Path) -> dict[str, str]:
    """sha256 of each existing relative path resolved against ``root``."""
    hashes: dict[str, str] = {}
    for relative in paths:
        candidate = root / relative
        if candidate.exists():
            hashes[relative] = hashlib.sha256(candidate.read_bytes()).hexdigest()
    return hashes


def load_recorded_hashes(out_dir: Path) -> dict[str, str] | None:
    """The ``files`` map of a result directory's ``PLAN_HASHES.json`` (or None)."""
    hashes_file = out_dir / HASHES_FILENAME
    if not hashes_file.exists():
        return None
    try:
        payload = json.loads(hashes_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    files = payload.get("files")
    return files if isinstance(files, dict) else None


def frozen_mismatches(out_dir: Path, root: Path) -> list[str]:
    """Recorded files whose current hash differs from the frozen record.

    Empty when the directory is not frozen yet or every recorded hash matches.
    """
    recorded = load_recorded_hashes(out_dir)
    if not recorded:
        return []
    mismatches: list[str] = []
    for relative, digest in recorded.items():
        candidate = root / relative
        current = hashlib.sha256(candidate.read_bytes()).hexdigest() if candidate.exists() else None
        if current != digest:
            mismatches.append(relative)
    return mismatches


def build_hashes_payload(
    dataset_id: str, code_revision: str, files: dict[str, str], *, label_version: str = "1.0"
) -> dict[str, object]:
    """The persisted ``PLAN_HASHES.json`` shape for one frozen result set."""
    return {
        "purpose": (
            "Content hashes of the frozen pre-registration and metric implementation "
            "used to produce this result set. Any change to these files invalidates the "
            "pre-registration and requires a new dataset_id."
        ),
        "algorithm": "sha256",
        "dataset_id": dataset_id,
        "label_version": label_version,
        "code_revision": code_revision,
        "files": files,
    }


__all__ = [
    "FROZEN_PATHS",
    "HASHES_FILENAME",
    "PIPELINE_FROZEN_PATHS",
    "build_hashes_payload",
    "content_hashes",
    "frozen_mismatches",
    "load_recorded_hashes",
    "sha256_file",
]

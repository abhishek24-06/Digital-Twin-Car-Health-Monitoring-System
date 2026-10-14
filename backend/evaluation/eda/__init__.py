"""Post-hoc exploratory data analysis for the Digital Twin evaluation.

This subpackage is **exploratory**, not part of the frozen pre-registration. It
reads the frozen evaluation artefacts read-only and produces a separate,
clearly-labelled EDA result set. Run it with ``python -m evaluation.eda``.
"""

from __future__ import annotations

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Entry point (delegates to :mod:`evaluation.eda.cli`)."""
    from evaluation.eda.cli import main as _main

    return _main(argv)

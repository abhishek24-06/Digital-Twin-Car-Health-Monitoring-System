"""Cross-platform helper for `make migration` (Phase 4, devtooling).

Generates an Alembic revision with autogenerate. The previous Makefile target
prompted with Bash's interactive ``read -p``, which does not exist on the
Windows command line; this helper drives the prompt through Python instead and
runs on every platform. The message can be supplied non-interactively via
``make migration MESSAGE="..."`` (the Makefile exports ``MESSAGE``).
"""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    message = os.environ.get("MESSAGE", "")
    if not message.strip():
        try:
            message = input("Message: ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
        if not message.strip():
            print("Migration message must not be empty.", file=sys.stderr)
            return 2

    command = [
        sys.executable,
        "-m",
        "alembic",
        "revision",
        "--autogenerate",
        "-m",
        message,
    ]
    return subprocess.call(command)


if __name__ == "__main__":
    sys.exit(main())

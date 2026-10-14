"""Run the Phase C MQTT integration suite against an isolated broker + DB.

Convenience wrapper for ``make mqtt-integration``. It only supplies a *default*
``DT_MQTT_TEST_DATABASE_URL``; every isolation rule still lives in
``tests/mqtt/conftest.py`` (loopback only, database named
``digital_twin_mqtt_test``, fail-closed otherwise). Any extra CLI arguments are
forwarded to pytest.

See ``docs/mqtt-integration-testing.md``.
"""

from __future__ import annotations

import os
import sys

import pytest

DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://postgres:root@127.0.0.1:5432/digital_twin_mqtt_test"
)


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("DT_MQTT_TEST_DATABASE_URL", DEFAULT_DATABASE_URL)
    args = ["-m", "mqtt_integration", "tests/mqtt", *(argv if argv is not None else sys.argv[1:])]
    return pytest.main(args)


if __name__ == "__main__":
    raise SystemExit(main())

import logging
import sys

_CONFIGURED = False


def configure_logging(debug: bool = False) -> None:
    """Configure the root logger once per process.

    In debug mode the console handler is more verbose. Log records use a
    simple structured-ish format that can be swapped for JSON formatters in
    a later phase without changing call sites.
    """
    global _CONFIGURED

    if _CONFIGURED:
        return

    level = logging.DEBUG if debug else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    # Avoid noisy third-party logs during normal operation.
    for noisy in ("uvicorn.access", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True

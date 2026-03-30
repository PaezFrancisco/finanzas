from __future__ import annotations

import logging
import os

from rich.logging import RichHandler


def setup_logging(*, verbose: bool = False, quiet: bool = False) -> None:
    """
    Configura logging para wallet_sync.
    - verbose (-v) → DEBUG
    - quiet (-q) → solo WARNING y superior
    - Si no: variable de entorno WALLET_LOG_LEVEL (por defecto INFO)
    """
    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.WARNING
    else:
        raw = os.environ.get("WALLET_LOG_LEVEL", "INFO").upper()
        level = getattr(logging, raw, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[
            RichHandler(
                rich_tracebacks=True,
                show_time=True,
                show_path=False,
                markup=True,
            )
        ],
        force=True,
    )

    logging.getLogger("urllib3").setLevel(logging.WARNING)

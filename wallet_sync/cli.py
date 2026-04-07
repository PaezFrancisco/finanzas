from __future__ import annotations

from pathlib import Path

import click

from wallet_sync import __version__
from wallet_sync.config import load_env
from wallet_sync.log_setup import setup_logging
from wallet_sync.sync import run_sync


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """Sincroniza gastos desde correo hacia CSV para tu wallet."""


@main.command("sync")
@click.option(
    "--project-root",
    type=click.Path(path_type=Path, file_okay=False, dir_okay=True),
    default=None,
    help="Raíz del proyecto (por defecto el directorio actual).",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Log detallado (DEBUG): cada correo, omisiones, etc.",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Solo advertencias y errores.",
)
def sync_cmd(project_root: Path | None, verbose: bool, quiet: bool) -> None:
    """Lee IMAP, compara con la BD y escribe el CSV solo con gastos nuevos."""
    if verbose and quiet:
        raise click.UsageError("Elige solo uno: --verbose (-v) o --quiet (-q).")
    root = project_root or Path.cwd()
    load_env(root)
    setup_logging(verbose=verbose, quiet=quiet)
    raise SystemExit(run_sync(root))


if __name__ == "__main__":
    main()

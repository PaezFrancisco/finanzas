from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

from wallet_sync.models import Expense
from wallet_sync.sinks.base import WalletSink

logger = logging.getLogger(__name__)


class CsvWalletSink(WalletSink):
    """CSV con columnas fijas para importar en la wallet: fecha, monto, moneda, comercio, descripcion."""

    HEADERS = ("fecha", "monto", "moneda", "comercio", "descripcion")

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def push(self, expenses: list[Expense]) -> None:
        if not expenses:
            logger.info("CSV: sin filas nuevas para [dim]%s[/dim]", self._path)
            return
        new_file = not self._path.is_file()
        with self._path.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(self.HEADERS))
            if new_file:
                w.writeheader()
            for e in expenses:
                w.writerow(
                    {
                        "fecha": e.occurred_on.isoformat() if e.occurred_on else "",
                        "monto": str(e.amount),
                        "moneda": e.currency,
                        "comercio": e.merchant,
                        "descripcion": e.description,
                    }
                )
        logger.info(
            "CSV: escritas [bold]%d[/bold] fila(s) en [bold]%s[/bold]%s",
            len(expenses),
            self._path.resolve(),
            " (archivo nuevo)" if new_file else "",
        )

    def replace_all(self, expenses: list[Expense]) -> None:
        """Sobrescribe el CSV con exactamente estas filas (ordenadas por fecha)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        sorted_rows = sorted(
            expenses,
            key=lambda e: (
                e.occurred_on or date.min,
                e.source,
                str(e.amount),
                e.description[:40],
            ),
        )
        with self._path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(self.HEADERS))
            w.writeheader()
            for e in sorted_rows:
                w.writerow(
                    {
                        "fecha": e.occurred_on.isoformat() if e.occurred_on else "",
                        "monto": str(e.amount),
                        "moneda": e.currency,
                        "comercio": e.merchant,
                        "descripcion": e.description,
                    }
                )
        logger.info(
            "CSV: archivo [bold]reemplazado[/bold] con [bold]%d[/bold] fila(s) en [bold]%s[/bold]",
            len(sorted_rows),
            self._path.resolve(),
        )

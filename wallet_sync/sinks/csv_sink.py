from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

from wallet_sync.models import Expense
from wallet_sync.sinks.base import WalletSink

logger = logging.getLogger(__name__)


def _row_sort_key(row: dict[str, str]) -> tuple[date, str, str]:
    try:
        d = date.fromisoformat((row.get("fecha") or "").strip())
    except ValueError:
        d = date.min
    return (d, str(row.get("comercio") or ""), str(row.get("stable_id") or ""))


class CsvWalletSink(WalletSink):
    """CSV para la wallet. Columna stable_id para trazabilidad. Siempre se reemplaza el archivo entero desde sync."""

    HEADERS = ("fecha", "monto", "moneda", "comercio", "descripcion", "stable_id")

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _expense_to_row(e: Expense) -> dict[str, str]:
        return {
            "fecha": e.occurred_on.isoformat() if e.occurred_on else "",
            "monto": str(e.amount),
            "moneda": e.currency,
            "comercio": e.merchant,
            "descripcion": e.description,
            "stable_id": e.stable_id(),
        }

    def push(self, expenses: list[Expense]) -> None:
        """Alias de replace_all (interfaz WalletSink)."""
        self.replace_all(expenses)

    def replace_all(self, expenses: list[Expense]) -> None:
        """Sobrescribe el CSV con exactamente estos gastos (ordenados por fecha)."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        rows = [self._expense_to_row(e) for e in expenses]
        sorted_rows = sorted(rows, key=_row_sort_key)
        with self._path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(self.HEADERS), extrasaction="ignore")
            w.writeheader()
            for row in sorted_rows:
                w.writerow({h: row.get(h, "") for h in self.HEADERS})
        logger.info(
            "CSV: archivo [bold]reemplazado[/bold] con [bold]%d[/bold] fila(s) en [bold]%s[/bold]",
            len(sorted_rows),
            self._path.resolve(),
        )

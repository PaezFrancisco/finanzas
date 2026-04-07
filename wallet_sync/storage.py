from __future__ import annotations

import sqlite3
from pathlib import Path

from wallet_sync.models import Expense


class DedupStore:
    """Evita volver a importar el mismo gasto."""

    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS imported (
                stable_id TEXT PRIMARY KEY,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """
        )
        self._conn.commit()

    def is_imported(self, stable_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM imported WHERE stable_id = ? LIMIT 1", (stable_id,)
        )
        return cur.fetchone() is not None

    def is_imported_expense(self, exp: Expense) -> bool:
        """True si cualquier variante de clave (canónica o legada) ya está en la BD."""
        for sid in exp.stable_id_candidates():
            if self.is_imported(sid):
                return True
        return False

    def mark_imported(self, stable_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO imported (stable_id) VALUES (?)", (stable_id,)
        )
        self._conn.commit()

    def mark_imported_expense(self, exp: Expense) -> None:
        """Registra todas las claves conocidas para este gasto (migración suave a formato canónico)."""
        for sid in exp.stable_id_candidates():
            self._conn.execute(
                "INSERT OR IGNORE INTO imported (stable_id) VALUES (?)", (sid,)
            )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

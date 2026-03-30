from __future__ import annotations

import sqlite3
from pathlib import Path


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

    def mark_imported(self, stable_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO imported (stable_id) VALUES (?)", (stable_id,)
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

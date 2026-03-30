from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any


@dataclass
class Expense:
    """Gasto normalizado listo para exportar a wallet."""

    amount: Decimal
    currency: str
    occurred_on: date | None
    merchant: str
    description: str
    source: str  # "santander" | "arq" | ...
    email_message_id: str
    raw_subject: str
    raw_snippet: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def stable_id(self) -> str:
        """Identificador para deduplicación (no depende del texto de descripción exportado)."""
        # "dolarapp" y "arq" son el mismo origen (rebranding); unifica claves viejas en BD.
        src = "arq" if self.source in ("arq", "dolarapp") else self.source
        return f"{src}|{self.email_message_id}|{self.amount}|{self.currency}"

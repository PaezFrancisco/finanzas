from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def _amount_dedup_key(amount: Decimal) -> str:
    """Clave estable para montos (evita 6000 vs 6000.00 en la deduplicación)."""
    q = Decimal("0.01")
    return format(amount.quantize(q, rounding=ROUND_HALF_UP), "f")


def _message_dedup_key(message_id: str, imap_uid: str) -> str:
    """
    Message-ID normalizado + reserva por UID IMAP cuando el header falta o es sintético.
    """
    mid = (message_id or "").strip()
    if mid.startswith("<") and mid.endswith(">"):
        mid = mid[1:-1].strip()
    mid_l = mid.lower()
    if re.match(r"^no-mid-", mid_l) or not mid_l:
        if (imap_uid or "").strip():
            return f"uid:{imap_uid.strip()}"
        return mid_l or "unknown"
    return mid_l


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
    imap_uid: str = ""

    def stable_id(self) -> str:
        """Identificador canónico para deduplicación (normaliza monto, moneda y mensaje)."""
        src = "arq" if self.source in ("arq", "dolarapp") else self.source
        mid = _message_dedup_key(self.email_message_id, self.imap_uid)
        amt = _amount_dedup_key(self.amount)
        cur = (self.currency or "").strip().upper()
        return f"{src}|{mid}|{amt}|{cur}"

    def stable_id_legacy_v0(self) -> str:
        """Formato antiguo (sin normalizar); se sigue consultando en BD para no duplicar imports viejos."""
        src = "arq" if self.source in ("arq", "dolarapp") else self.source
        return f"{src}|{self.email_message_id}|{self.amount}|{self.currency}"

    def stable_id_candidates(self) -> list[str]:
        """Todas las claves que pueden corresponder a este gasto en `sync_state.db`."""
        seen: set[str] = set()
        out: list[str] = []
        for s in (self.stable_id(), self.stable_id_legacy_v0()):
            if s and s not in seen:
                seen.add(s)
                out.append(s)
        return out

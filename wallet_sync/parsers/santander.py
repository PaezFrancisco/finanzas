from __future__ import annotations

import re
from decimal import Decimal

from wallet_sync.email_client import RawEmail, extract_money_ar, parse_amount_token
from wallet_sync.models import Expense
from wallet_sync.parsers.base import Parser


def _parse_santander_importe(text: str) -> Decimal | None:
    norm = re.sub(r"\s+", " ", text)
    m = re.search(
        r"(?i)importe\D{0,800}?\$\s*([\d]{1,3}(?:\.\d{3})*,\d{2})",
        norm,
    )
    if m:
        return parse_amount_token(m.group(1))
    for m2 in re.finditer(r"(?i)\$\s*([\d]{1,3}(?:\.\d{3})*,\d{2})", norm):
        amt = parse_amount_token(m2.group(1))
        if amt is not None and amt > 0:
            return amt
    return None


def _parse_santander_destinatario(norm: str) -> str | None:
    m = re.search(r"(?i)destinatario\D{0,200}?(\d{8,22})\b", norm)
    if m:
        return m.group(1)
    return None


class SantanderParser(Parser):
    """
    Avisos tipo «Aviso de transferencia» desde mails.santander.com.ar (HTML).
    Importe: $ 20.000,00 junto a la fila Importe.
    """

    name = "santander"

    def __init__(
        self,
        from_keywords: list[str],
        subject_contains: list[str] | None = None,
    ) -> None:
        self._kw = [k.lower() for k in from_keywords]
        self._subj = [s.lower() for s in (subject_contains or [])]

    def match(self, raw: RawEmail) -> bool:
        from_l = raw.from_addr.lower()
        if not any(k in from_l for k in self._kw):
            return False
        if not self._subj:
            return True
        sub = raw.subject.lower()
        return any(s in sub for s in self._subj)

    def parse(self, raw: RawEmail) -> list[Expense]:
        text = f"{raw.subject}\n{raw.body_text}"
        norm = re.sub(r"\s+", " ", text)
        occurred = raw.date.date() if raw.date else None

        amt = _parse_santander_importe(text)
        if amt is None:
            amounts = extract_money_ar(text)
            if amounts:
                amounts.sort(key=lambda x: x[1], reverse=True)
                amt = amounts[0][1]

        if amt is None:
            return []

        dest = _parse_santander_destinatario(norm)
        merchant = f"Transferencia {dest}" if dest else "Santander transferencia"

        return [
            Expense(
                amount=amt,
                currency="ARS",
                occurred_on=occurred,
                merchant=merchant[:120],
                description=f"Santander — {raw.subject[:120]}",
                source=self.name,
                email_message_id=raw.message_id,
                raw_subject=raw.subject,
                raw_snippet=text[:500],
            )
        ]

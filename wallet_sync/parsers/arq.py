from __future__ import annotations

import re

from wallet_sync.email_client import RawEmail, extract_money_ar, parse_amount_flexible
from wallet_sync.models import Expense
from wallet_sync.parsers.base import Parser


class ArqParser(Parser):
    """
    ARQ (antes DolarApp): correos desde no-reply@dolarapp.com u otros dominios ARQ;
    transferencias tipo «Enviaste 20,000 ARS a NOMBRE».
    """

    name = "arq"

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
        subj = raw.subject.strip()
        text = f"{raw.subject}\n{raw.body_text}"
        occurred = raw.date.date() if raw.date else None

        m = re.search(r"(?i)Enviaste\s+([\d.,]+)\s*ARS\s+a\s+(.+)$", subj)
        if m:
            amt = parse_amount_flexible(m.group(1))
            merchant = re.sub(r"\s+", " ", m.group(2).strip())[:120]
            if amt is not None:
                return [
                    Expense(
                        amount=amt,
                        currency="ARS",
                        occurred_on=occurred,
                        merchant=merchant or "ARQ",
                        description=f"ARQ — {raw.subject[:120]}",
                        source=self.name,
                        email_message_id=raw.message_id,
                        raw_subject=raw.subject,
                        raw_snippet=text[:500],
                        imap_uid=raw.imap_uid,
                    )
                ]

        m2 = re.search(
            r"(?i)debitado\s+([\d.,]+)\s*ARS",
            raw.body_text,
        )
        if m2:
            amt = parse_amount_flexible(m2.group(1))
            if amt is not None:
                merchant = self._guess_payee(text) or "ARQ"
                return [
                    Expense(
                        amount=amt,
                        currency="ARS",
                        occurred_on=occurred,
                        merchant=merchant,
                        description=f"ARQ — {raw.subject[:120]}",
                        source=self.name,
                        email_message_id=raw.message_id,
                        raw_subject=raw.subject,
                        raw_snippet=text[:500],
                        imap_uid=raw.imap_uid,
                    )
                ]

        amounts = extract_money_ar(text)
        if not amounts:
            return []
        amounts.sort(key=lambda x: x[1], reverse=True)
        cur, amt = amounts[0]
        return [
            Expense(
                amount=amt,
                currency=cur,
                occurred_on=occurred,
                merchant=self._guess_payee(text) or "ARQ",
                description=f"ARQ — {raw.subject[:120]}",
                source=self.name,
                email_message_id=raw.message_id,
                raw_subject=raw.subject,
                raw_snippet=text[:500],
                imap_uid=raw.imap_uid,
            )
        ]

    def _guess_payee(self, text: str) -> str | None:
        m = re.search(
            r"(?i)transferencia\s+a\s+([^\n\r.]{2,80})",
            text,
        )
        if m:
            return m.group(1).strip()[:120]
        m2 = re.search(r"(?i)destinatario\D{0,120}?([A-ZÁÉÍÓÚÑ][^\n\r]{2,60})", text)
        if m2:
            return m2.group(1).strip()[:120]
        return None


# Compatibilidad con imports antiguos
DolarAppParser = ArqParser

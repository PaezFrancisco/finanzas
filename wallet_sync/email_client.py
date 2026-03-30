from __future__ import annotations

import email
import html as html_module
import imaplib
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.message import Message
from typing import Iterator

logger = logging.getLogger(__name__)


@dataclass
class RawEmail:
    message_id: str
    subject: str
    from_addr: str
    date: datetime | None
    body_text: str


def _html_to_text(html: str) -> str:
    """Quita etiquetas HTML para poder parsear montos en mails solo-HTML (p. ej. Santander)."""
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<\s*br\s*/?>", "\n", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = html_module.unescape(html)
    return re.sub(r"\s+", " ", html).strip()


def _decode_mime_header(value: str) -> str:
    parts: list[str] = []
    for fragment, charset in decode_header(value):
        if isinstance(fragment, bytes):
            parts.append(fragment.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(fragment)
    return "".join(parts).strip()


def _get_body_text(msg: Message) -> str:
    plain_chunks: list[str] = []
    html_chunks: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp.lower():
                continue
            ctype = part.get_content_type()
            payload = part.get_payload(decode=True)
            if not payload or not isinstance(payload, (bytes, bytearray)):
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if ctype == "text/plain":
                plain_chunks.append(decoded)
            elif ctype == "text/html":
                html_chunks.append(_html_to_text(decoded))
        if plain_chunks:
            return "\n".join(plain_chunks)
        if html_chunks:
            return "\n".join(html_chunks)
        return ""
    ctype = msg.get_content_type()
    payload = msg.get_payload(decode=True)
    if isinstance(payload, bytes):
        decoded = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
        if ctype == "text/html":
            return _html_to_text(decoded)
        return decoded
    return str(payload or "")


def _parse_date(date_hdr: str | None) -> datetime | None:
    if not date_hdr:
        return None
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(date_hdr)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


class ImapClient:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        mailbox: str = "INBOX",
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._mailbox = mailbox
        self._imap: imaplib.IMAP4_SSL | None = None

    def __enter__(self) -> ImapClient:
        logger.info(
            "IMAP: conectando a [bold]%s:%s[/bold], usuario=[bold]%s[/bold], carpeta=[bold]%s[/bold]",
            self._host,
            self._port,
            self._user,
            self._mailbox,
        )
        self._imap = imaplib.IMAP4_SSL(self._host, self._port)
        self._imap.login(self._user, self._password)
        self._imap.select(self._mailbox)
        logger.info("IMAP: sesión iniciada correctamente.")
        return self

    def __exit__(self, *args: object) -> None:
        if self._imap:
            try:
                self._imap.close()
            except Exception:
                pass
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None
            logger.info("IMAP: sesión cerrada.")

    def search_since(self, since: datetime) -> list[bytes]:
        assert self._imap is not None
        # SINCE usa fecha sin hora en servidor IMAP
        date_str = since.strftime("%d-%b-%Y")
        status, data = self._imap.search(None, f'SINCE {date_str}')
        if status != "OK" or not data or not data[0]:
            return []
        return data[0].split()

    def search_since_from_hints(self, since: datetime, from_substrings: list[str]) -> list[bytes]:
        """
        UIDs con SINCE y FROM que contenga cada subcadena (unión).
        Reduce tráfico frente a bajar todos los mails del rango.
        """
        assert self._imap is not None
        date_str = since.strftime("%d-%b-%Y")
        if not from_substrings:
            return self.search_since(since)
        uids: set[bytes] = set()
        for hint in from_substrings:
            h = hint.strip()
            if not h:
                continue
            try:
                status, data = self._imap.search(None, f'(SINCE {date_str}) FROM "{h}"')
            except Exception as e:
                logger.warning("IMAP SEARCH FROM %r falló: %s — se omite esta pista.", h, e)
                continue
            if status != "OK" or not data or not data[0]:
                continue
            uids.update(data[0].split())
        def _uid_int(b: bytes) -> int:
            try:
                return int(b)
            except ValueError:
                return 0

        return sorted(uids, key=_uid_int)

    def fetch_email(self, uid: bytes) -> RawEmail | None:
        assert self._imap is not None
        status, data = self._imap.fetch(uid, "(RFC822)")
        if status != "OK" or not data or not isinstance(data[0], tuple):
            return None
        raw = data[0][1]
        if not isinstance(raw, (bytes, bytearray)):
            return None
        msg = email.message_from_bytes(raw)
        mid = msg.get("Message-ID") or ""
        if not mid:
            mid = f"no-mid-{uid.decode(errors='replace')}"
        subject = _decode_mime_header(msg.get("Subject") or "")
        from_addr = _decode_mime_header(msg.get("From") or "")
        date_hdr = msg.get("Date")
        dt = _parse_date(date_hdr)
        body = _get_body_text(msg)
        return RawEmail(
            message_id=mid.strip(),
            subject=subject,
            from_addr=from_addr,
            date=dt,
            body_text=body,
        )

    def iter_recent(
        self,
        lookback_days: int,
        filter_from: list[str] | None = None,
        filter_subject: list[str] | None = None,
        imap_from_hints: list[str] | None = None,
    ) -> Iterator[RawEmail]:
        since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        hints = [h.strip() for h in (imap_from_hints or []) if h and h.strip()]
        if hints:
            uids = self.search_since_from_hints(since, hints)
            logger.info(
                "Buzón: [bold]%d[/bold] UID(s) con ventana [bold]%s días[/bold] (desde %s) y filtro IMAP FROM [bold]%s[/bold].",
                len(uids),
                lookback_days,
                since.date().isoformat(),
                hints,
            )
        else:
            uids = self.search_since(since)
            logger.info(
                "Buzón: [bold]%d[/bold] UID(s) en ventana [bold]%s días[/bold] (desde %s), sin filtro por remitente (revisa [bold]imap_from_hints[/bold] en config).",
                len(uids),
                lookback_days,
                since.date().isoformat(),
            )
        if not uids:
            logger.warning(
                "No hay mensajes en ese rango. Prueba a subir [bold]lookback_days[/bold] en config o revisa la fecha del servidor."
            )
        fl_from = [f.lower() for f in (filter_from or [])]
        fl_sub = [s.lower() for s in (filter_subject or [])]

        for uid in uids:
            raw = self.fetch_email(uid)
            if not raw:
                logger.warning("No se pudo leer el mensaje UID=%s", uid.decode(errors="replace"))
                continue
            logger.debug(
                "UID=%s | De: %s | Asunto: %s",
                uid.decode(errors="replace"),
                raw.from_addr[:120],
                raw.subject[:200],
            )
            combined = f"{raw.from_addr} {raw.subject} {raw.body_text[:500]}".lower()
            if fl_from and not any(x in combined for x in fl_from):
                # también buscar en from explícito
                from_low = raw.from_addr.lower()
                if not any(x in from_low for x in fl_from):
                    continue
            if fl_sub and not any(s in raw.subject.lower() for s in fl_sub):
                continue
            yield raw


def parse_amount_token(raw: str) -> Decimal | None:
    """Interpreta montos tipo 1.234,56 (AR) o 1234.56."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        if re.match(r"^\d{1,3}(\.\d{3})+,\d{2}$", raw):
            return Decimal(raw.replace(".", "").replace(",", "."))
        if "," in raw and "." in raw and raw.rfind(",") > raw.rfind("."):
            return Decimal(raw.replace(".", "").replace(",", "."))
        if "," in raw and "." not in raw:
            return Decimal(raw.replace(",", "."))
        return Decimal(raw.replace(",", ""))
    except Exception:
        return None


def parse_amount_flexible(raw: str) -> Decimal | None:
    """Montos tipo 20,000 o 20.000 (solo miles) como en asuntos ARQ (ex DolarApp)."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        if re.match(r"^\d{1,3}(?:,\d{3})+$", raw):
            return Decimal(raw.replace(",", ""))
        if re.match(r"^\d{1,3}(?:\.\d{3})+$", raw):
            return Decimal(raw.replace(".", ""))
    except Exception:
        pass
    return parse_amount_token(raw)


def extract_money_ar(text: str) -> list[tuple[str, Decimal]]:
    """
    Extrae montos: moneda antes del número, monto+ARS, y $ + formato AR (20.000,00).
    """
    results: list[tuple[str, Decimal]] = []
    seen: set[tuple[str, Decimal]] = set()

    def add(cur: str, raw_num: str) -> None:
        amt = parse_amount_flexible(raw_num) or parse_amount_token(raw_num)
        if amt is None:
            return
        key = (cur, amt)
        if key in seen:
            return
        seen.add(key)
        results.append(key)

    # Moneda antes del número: ARS 123 / $ 20.000,00
    pattern = re.compile(
        r"(ARS|USD|U\$S|\$)\s*:?\s*([\d]{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:[.,]\d{1,2})?)",
        re.IGNORECASE,
    )
    for m in pattern.finditer(text):
        label = m.group(1).upper()
        raw_num = m.group(2)
        cur = "USD" if label in ("USD", "U$S") else "ARS"
        add(cur, raw_num)

    # Número + ARS (p. ej. "20,000 ARS", "Hemos debitado 20,000 ARS")
    for m in re.finditer(
        r"(?i)([\d]{1,3}(?:[.,]\d{3})+(?:,\d{2})?|[\d]{1,3}(?:[.,]\d{3})+)\s*ARS\b",
        text,
    ):
        add("ARS", m.group(1))

    # Santander / banca AR: $ 20.000,00 (importe en pesos)
    for m in re.finditer(r"(?i)\$\s*([\d]{1,3}(?:\.\d{3})*,\d{2})", text):
        add("ARS", m.group(1))

    return results

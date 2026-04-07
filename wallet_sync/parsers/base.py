from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wallet_sync.email_client import RawEmail
    from wallet_sync.models import Expense


class Parser(ABC):
    name: str

    @abstractmethod
    def match(self, raw: RawEmail) -> bool:
        """¿Este parser debe procesar este correo?"""

    @abstractmethod
    def parse(self, raw: RawEmail) -> list[Expense]:
        """Extrae uno o más gastos del correo."""


def parse_with_chain(raw: RawEmail, parsers: list[Parser]) -> list[Expense]:
    """
    Solo el primer parser que hace match procesa el correo (evita duplicar si varios matchean).
    """
    for p in parsers:
        if p.match(raw):
            return p.parse(raw)
    return []

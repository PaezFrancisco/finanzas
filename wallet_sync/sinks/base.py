from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wallet_sync.models import Expense


class WalletSink(ABC):
    @abstractmethod
    def push(self, expenses: list[Expense]) -> None:
        """Envía gastos nuevos al destino (CSV, API, etc.)."""

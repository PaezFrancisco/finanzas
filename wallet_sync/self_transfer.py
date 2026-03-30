from __future__ import annotations

from typing import Any

from wallet_sync.config import arq_source_config
from wallet_sync.models import Expense

_ARQ_SOURCES = frozenset({"arq", "dolarapp"})


def _hints_match(exp: Expense, hints: list[str]) -> bool:
    if not hints:
        return False
    blob = f"{exp.merchant} {exp.description} {exp.raw_subject} {exp.raw_snippet}".lower()
    return any(h.strip().lower() in blob for h in hints if h and str(h).strip())


def should_skip_as_self_transfer(exp: Expense, cfg: dict[str, Any]) -> bool:
    """
    Transferencias entre cuentas propias (p. ej. ARQ → Santander): no son un
    gasto nuevo, solo movimiento de fondos. Si coinciden las pistas configuradas,
    no se exporta al CSV pero sí se marca como procesado en la BD.
    """
    if exp.source in _ARQ_SOURCES:
        block = arq_source_config(cfg).get("self_transfer") or {}
        if not block.get("enabled"):
            return False
        hints = list(block.get("match_hints") or [])
        return _hints_match(exp, hints)

    if exp.source == "santander":
        block = (cfg.get("sources") or {}).get("santander") or {}
        block = block.get("self_transfer") or {}
        if not block.get("enabled"):
            return False
        hints = list(block.get("match_hints") or [])
        return _hints_match(exp, hints)

    return False

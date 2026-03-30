from __future__ import annotations

from dataclasses import replace
from typing import Any

from wallet_sync.config import arq_source_config
from wallet_sync.models import Expense


def apply_arq_wallet_rules(expense: Expense, cfg: dict[str, Any]) -> Expense:
    """
    Enriquece la descripción para dejar explícito en qué cuenta de tu wallet debe
    imputarse el gasto (p. ej. USD) cuando el mail muestra la operación en otra
    moneda (p. ej. ARS tras conversión en ARQ).

    El CSV sigue llevando monto/moneda del mail (hecho real del aviso); la línea
    de descripción indica que el descuento de saldo debe hacerse en USD.
    """
    if expense.source not in ("arq", "dolarapp"):
        return expense
    src = arq_source_config(cfg)
    wallet_ccy = (src.get("wallet_impute_currency") or "").strip()
    if not wallet_ccy:
        return expense

    tpl = (src.get("wallet_impute_description_template") or "").strip()
    if not tpl:
        tpl = (
            "[Cuenta {wallet_currency}] Imputar en saldo {wallet_currency}; "
            "operación en {currency} según mail: {amount}. {description}"
        )

    try:
        new_desc = tpl.format(
            wallet_currency=wallet_ccy,
            amount=expense.amount,
            currency=expense.currency,
            merchant=expense.merchant,
            description=expense.description,
        )
    except KeyError:
        new_desc = f"[Cuenta {wallet_ccy}] {expense.description}"

    return replace(expense, description=new_desc.strip())


def apply_dolarapp_wallet_rules(expense: Expense, cfg: dict[str, Any]) -> Expense:
    """Alias retrocompatible; usar `apply_arq_wallet_rules`."""
    return apply_arq_wallet_rules(expense, cfg)

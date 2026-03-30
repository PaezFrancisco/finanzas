from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal

from wallet_sync.models import Expense

logger = logging.getLogger(__name__)

_ARQ_SOURCES = frozenset({"arq", "dolarapp"})


def _sum_ars_by_day(
    expenses: list[Expense],
    sources: frozenset[str] | set[str],
) -> dict[date, Decimal]:
    by_day: dict[date, Decimal] = defaultdict(lambda: Decimal(0))
    for e in expenses:
        if e.occurred_on is None:
            continue
        if e.currency != "ARS":
            continue
        if e.source not in sources:
            continue
        by_day[e.occurred_on] += e.amount
    return dict(by_day)


def log_daily_ars_for_reconciliation(expenses: list[Expense]) -> None:
    """
    Después de generar el CSV: totales en ARS por día para cruzar en ARQ
    cuántos USD convertiste cada fecha (los montos del mail siguen en ARS).
    """
    if not expenses:
        return

    arq_by = _sum_ars_by_day(expenses, _ARQ_SOURCES)
    san_by = _sum_ars_by_day(expenses, frozenset({"santander"}))

    all_days = sorted(set(arq_by) | set(san_by))
    if not all_days:
        logger.info(
            "Resumen diario ARS: no hay filas con [bold]fecha[/bold] y [bold]moneda ARS[/bold] en este lote."
        )
        return

    logger.info(
        "[bold cyan]── ARS por día (este sync) — para cruzar con ARQ / tu wallet ──[/bold cyan]"
    )
    logger.info(
        "En la app ARQ revisá cuántos [bold]USD[/bold] convertiste cada fecha; "
        "los importes de abajo son [bold]ARS[/bold] del CSV (mismo criterio que el mail)."
    )

    total_arq = Decimal(0)
    total_san = Decimal(0)

    for d in all_days:
        a = arq_by.get(d, Decimal(0))
        s = san_by.get(d, Decimal(0))
        line_parts = [f"[bold]{d.isoformat()}[/bold]"]
        if a > 0:
            line_parts.append(f"ARQ: [bold]{_fmt_ars(a)}[/bold] ARS")
            total_arq += a
        if s > 0:
            line_parts.append(f"Santander: [bold]{_fmt_ars(s)}[/bold] ARS")
            total_san += s
        day_total = a + s
        line_parts.append(f"→ día [bold]{_fmt_ars(day_total)}[/bold] ARS")
        logger.info("  %s", " │ ".join(line_parts))

    grand = total_arq + total_san
    if grand > 0:
        tail = []
        if total_arq > 0:
            tail.append(f"ARQ [bold]{_fmt_ars(total_arq)}[/bold] ARS")
        if total_san > 0:
            tail.append(f"Santander [bold]{_fmt_ars(total_san)}[/bold] ARS")
        logger.info(
            "  [dim]Total este sync:[/dim] [bold]%s[/bold] ARS (%s)",
            _fmt_ars(grand),
            " · ".join(tail) if tail else "",
        )
    logger.info(
        "[dim]Tip:[/dim] en ARQ, filtrá por fecha y sumá los [bold]USD[/bold] que convertiste cada día; "
        "cargá ese total en tu cuenta USD de la wallet (el CSV sigue en ARS como el mail)."
    )


def _fmt_ars(n: Decimal) -> str:
    """Formato legible sin forzar locale del sistema."""
    if n == n.to_integral():
        return format(int(n), ",").replace(",", ".")
    return str(n)

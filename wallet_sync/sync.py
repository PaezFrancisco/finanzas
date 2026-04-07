from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from wallet_sync.config import arq_source_config, imap_settings_from_env, merged_config
from wallet_sync.email_client import ImapClient
from wallet_sync.models import Expense
from wallet_sync.parsers import ArqParser, SantanderParser, parse_with_chain
from wallet_sync.post_export import log_daily_ars_for_reconciliation
from wallet_sync.self_transfer import should_skip_as_self_transfer
from wallet_sync.sinks import CsvWalletSink, WalletSink
from wallet_sync.storage import DedupStore
from wallet_sync.wallet_export import apply_arq_wallet_rules

logger = logging.getLogger(__name__)


def _imap_from_hints(cfg: dict[str, Any]) -> list[str]:
    """Subcadenas para IMAP SEARCH FROM (unión); vacío = revisar todo el rango."""
    out: list[str] = []
    for key in ("santander", "arq", "dolarapp"):
        src = (cfg.get("sources") or {}).get(key) or {}
        if not src.get("enabled", True):
            continue
        for h in src.get("imap_from_hints") or []:
            h = str(h).strip()
            if h:
                out.append(h)
    seen: set[str] = set()
    deduped: list[str] = []
    for h in out:
        if h not in seen:
            seen.add(h)
            deduped.append(h)
    return deduped


def _build_parsers(cfg: dict[str, Any]) -> list:
    parsers: list = []
    sources = cfg.get("sources") or {}
    s = sources.get("santander") or {}
    if s.get("enabled", True):
        parsers.append(
            SantanderParser(
                from_keywords=list(
                    s.get("from_contains")
                    or ["santander.com.ar", "mails.santander.com.ar"]
                ),
                subject_contains=list(
                    s.get("subject_contains") or ["aviso de transferencia"]
                ),
            )
        )
    d = arq_source_config(cfg)
    if d.get("enabled", True):
        parsers.append(
            ArqParser(
                from_keywords=list(
                    d.get("from_contains") or ["dolarapp.com", "arqfinance.com"]
                ),
                subject_contains=list(d.get("subject_contains") or ["enviaste"]),
            )
        )
    return parsers


def _build_sinks(cfg: dict[str, Any], project_root: Path) -> list[WalletSink]:
    w = cfg.get("wallet") or {}
    project_root = project_root.resolve()
    path = project_root / (w.get("csv_path") or "./data/gastos_wallet.csv")
    return [CsvWalletSink(path)]


def run_sync(project_root: Path | None = None) -> int:
    """
    1) Lee el correo (ventana lookback_days).
    2) Por cada gasto parseado: si ya está en sync_state.db, se descarta.
    3) Reemplaza el CSV entero solo con los gastos nuevos (no estaban en la BD).
    4) Marca en la BD los gastos exportados.
    """
    root = project_root or Path.cwd()
    cfg = merged_config(root)
    lookback = int(cfg.get("lookback_days") or 30)
    imap_cfg = imap_settings_from_env()

    yaml_used = root / "config.yaml"
    if not yaml_used.is_file():
        yaml_used = root / "config.example.yaml"
    logger.info("Config YAML: [bold]%s[/bold]", yaml_used.resolve())

    if not imap_cfg.get("user") or not imap_cfg.get("password"):
        logger.error(
            "Falta configuración IMAP. Define [bold]IMAP_USER[/bold] e [bold]IMAP_PASSWORD[/bold] en .env (ver .env.example)."
        )
        return 1

    parsers = _build_parsers(cfg)
    if not parsers:
        logger.warning("No hay parsers habilitados en config.yaml.")
        return 0

    imap_hints = _imap_from_hints(cfg)
    logger.info(
        "Parsers activos: [bold]%s[/bold] | lookback: [bold]%s[/bold] días | IMAP FROM: [bold]%s[/bold]",
        ", ".join(p.name for p in parsers),
        lookback,
        imap_hints if imap_hints else "(todos los remitentes en el rango)",
    )

    state_path = root / (cfg.get("state_db_path") or "./data/sync_state.db")
    store = DedupStore(state_path)
    logger.info("Base de deduplicación: [bold]%s[/bold]", state_path.resolve())

    w_cfg = cfg.get("wallet") or {}
    sinks = _build_sinks(cfg, root)
    csv_path = (root.resolve() / (w_cfg.get("csv_path") or "./data/gastos_wallet.csv")).resolve()
    for s in sinks:
        logger.info("Destino de salida: [bold]%s[/bold]", type(s).__name__)
    logger.info(
        "CSV: [bold]%s[/bold] — en cada sync se [bold]reemplaza[/bold] el archivo solo con gastos "
        "[bold]nuevos[/bold] (no presentes en la BD antes de este run).",
        csv_path,
    )

    # Un gasto por stable_id en esta corrida (mismo mail duplicado → una entrada)
    por_sid: dict[str, Expense] = {}
    emails_processed = 0
    gastos_parseados = 0
    omitidos_transferencia_propia = 0

    try:
        try:
            with ImapClient(
                host=imap_cfg["host"],
                port=imap_cfg["port"],
                user=imap_cfg["user"],
                password=imap_cfg["password"],
                mailbox=imap_cfg.get("mailbox", "INBOX"),
            ) as imap:
                for raw in imap.iter_recent(
                    lookback_days=lookback,
                    filter_from=[],
                    filter_subject=[],
                    imap_from_hints=imap_hints,
                ):
                    emails_processed += 1
                    for exp in parse_with_chain(raw, parsers):
                        gastos_parseados += 1
                        if should_skip_as_self_transfer(exp, cfg):
                            store.mark_imported_expense(exp)
                            omitidos_transferencia_propia += 1
                            logger.info(
                                "[yellow]Omitido (transferencia propia entre cuentas):[/yellow] "
                                "[bold]%s[/bold] %s %s — %s",
                                exp.source,
                                exp.amount,
                                exp.currency,
                                exp.description[:100],
                            )
                            continue
                        por_sid[exp.stable_id()] = exp
        except Exception:
            logger.exception("Error durante la conexión o lectura IMAP")
            return 1

        en_correo = list(por_sid.values())
        duplicados_bd = 0
        nuevos: list[Expense] = []
        for exp in en_correo:
            if store.is_imported_expense(exp):
                duplicados_bd += 1
                logger.debug(
                    "Descartado (ya en BD): %s | %s %s",
                    exp.stable_id(),
                    exp.source,
                    exp.description[:70],
                )
                continue
            nuevos.append(exp)
            logger.info(
                "A exportar (no estaba en la BD): [bold]%s[/bold] %s %s — %s",
                exp.source,
                exp.amount,
                exp.currency,
                exp.description[:100],
            )

        to_export = [apply_arq_wallet_rules(e, cfg) for e in nuevos]

        for sink in sinks:
            if hasattr(sink, "replace_all"):
                sink.replace_all(to_export)
            else:
                sink.push(to_export)

        for exp in nuevos:
            store.mark_imported_expense(exp)

        logger.info(
            "Resumen: mensajes=[bold]%d[/bold] | parseados=[bold]%d[/bold] | "
            "omitidos transferencia propia=[bold]%d[/bold] | ya en BD (descartados)=[bold]%d[/bold] | "
            "[green]nuevos en CSV=[bold]%d[/bold][/green]",
            emails_processed,
            gastos_parseados,
            omitidos_transferencia_propia,
            duplicados_bd,
            len(nuevos),
        )
        if nuevos:
            logger.info(
                "[green]CSV reemplazado con [bold]%d[/bold] fila(s) nueva(s).[/green]",
                len(nuevos),
            )
            log_daily_ars_for_reconciliation(nuevos)
        else:
            logger.info(
                "[dim]Nada nuevo respecto a la BD: CSV con solo encabezado.[/dim]"
            )
    finally:
        store.close()

    return 0

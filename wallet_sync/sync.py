from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from wallet_sync.config import imap_settings_from_env, merged_config
from wallet_sync.email_client import ImapClient
from wallet_sync.models import Expense
from wallet_sync.config import arq_source_config
from wallet_sync.parsers import ArqParser, SantanderParser, parse_with_chain
from wallet_sync.storage import DedupStore
from wallet_sync.sinks import CsvWalletSink, WalletSink
from wallet_sync.post_export import log_daily_ars_for_reconciliation
from wallet_sync.self_transfer import should_skip_as_self_transfer
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

    sinks = _build_sinks(cfg, root)
    for s in sinks:
        logger.info("Destino de salida: [bold]%s[/bold]", type(s).__name__)

    w_cfg = cfg.get("wallet") or {}
    csv_mode = str(w_cfg.get("csv_mode") or "append").lower().strip()
    csv_replace = csv_mode in ("replace", "overwrite", "rewrite")
    if csv_mode not in ("append", "replace", "overwrite", "rewrite"):
        logger.warning(
            "wallet.csv_mode=[bold]%s[/bold] no reconocido; uso [bold]append[/bold]. Valores: append, replace.",
            csv_mode,
        )
        csv_replace = False
    if csv_replace:
        logger.info(
            "Modo CSV: [bold]replace[/bold] — el archivo se [bold]sobrescribe[/bold] con los movimientos "
            "de la ventana IMAP ([bold]%s[/bold] días); no se acumulan duplicados en el archivo.",
            lookback,
        )

    new_expenses: list[Expense] = []
    by_stable: dict[str, Expense] = {}
    emails_processed = 0
    gastos_parseados = 0
    duplicados = 0
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
                            store.mark_imported(exp.stable_id())
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
                        if csv_replace:
                            sid = exp.stable_id()
                            by_stable[sid] = exp
                            logger.debug(
                                "Ventana replace: %s %s %s — %s",
                                exp.source,
                                exp.amount,
                                exp.currency,
                                exp.description[:80],
                            )
                            continue
                        if store.is_imported(exp.stable_id()):
                            duplicados += 1
                            logger.debug(
                                "Omitido (ya importado): %s %s %s",
                                exp.source,
                                exp.amount,
                                exp.description[:60],
                            )
                            continue
                        new_expenses.append(exp)
                        logger.info(
                            "Nuevo gasto: [bold]%s[/bold] %s %s — %s",
                            exp.source,
                            exp.amount,
                            exp.currency,
                            exp.description[:100],
                        )
        except Exception:
            logger.exception("Error durante la conexión o lectura IMAP")
            return 1

        if csv_replace:
            all_for_csv = list(by_stable.values())
            logger.info(
                "Resumen buzón: mensajes revisados=[bold]%d[/bold] | gastos detectados por parsers=[bold]%d[/bold] | "
                "omitidos (transferencia propia)=[bold]%d[/bold] | "
                "[green]movimientos únicos en ventana=[bold]%d[/bold][/green] (CSV reemplazado)",
                emails_processed,
                gastos_parseados,
                omitidos_transferencia_propia,
                len(all_for_csv),
            )
            to_export = [apply_arq_wallet_rules(e, cfg) for e in all_for_csv]
            for sink in sinks:
                if hasattr(sink, "replace_all"):
                    sink.replace_all(to_export)
                else:
                    sink.push(to_export)
            for exp in all_for_csv:
                store.mark_imported(exp.stable_id())
            if all_for_csv:
                logger.info(
                    "[green]CSV actualizado: [bold]%d[/bold] fila(s) en la ventana de fechas.[/green]",
                    len(all_for_csv),
                )
                log_daily_ars_for_reconciliation(all_for_csv)
            else:
                for sink in sinks:
                    if hasattr(sink, "replace_all"):
                        sink.replace_all([])
                logger.info(
                    "No hay movimientos en la ventana (CSV dejado solo con encabezado)."
                )
        else:
            logger.info(
                "Resumen buzón: mensajes revisados=[bold]%d[/bold] | gastos detectados por parsers=[bold]%d[/bold] | "
                "ya estaban importados=[bold]%d[/bold] | omitidos (transferencia propia)=[bold]%d[/bold] | "
                "[green]nuevos a exportar=[bold]%d[/bold][/green]",
                emails_processed,
                gastos_parseados,
                duplicados,
                omitidos_transferencia_propia,
                len(new_expenses),
            )
            to_export = [apply_arq_wallet_rules(e, cfg) for e in new_expenses]
            for sink in sinks:
                sink.push(to_export)
            for exp in new_expenses:
                store.mark_imported(exp.stable_id())
            if new_expenses:
                logger.info(
                    "[green]Exportación completada: [bold]%d[/bold] gasto(s) nuevo(s) guardados.[/green]",
                    len(new_expenses),
                )
                log_daily_ars_for_reconciliation(new_expenses)
            else:
                logger.info(
                    "No se añadieron gastos nuevos (o no hubo coincidencias con Santander/ARQ en el texto del mail)."
                )
    finally:
        store.close()

    return 0

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def load_env(project_root: Path | None = None) -> None:
    root = project_root or Path.cwd()
    load_dotenv(root / ".env", override=False)


def load_yaml_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def imap_settings_from_env() -> dict[str, Any]:
    return {
        "host": os.environ.get("IMAP_HOST", "imap.gmail.com"),
        "port": int(os.environ.get("IMAP_PORT", "993")),
        "user": os.environ.get("IMAP_USER", ""),
        "password": os.environ.get("IMAP_PASSWORD", ""),
        "mailbox": os.environ.get("IMAP_MAILBOX", "INBOX"),
    }


def arq_source_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Preferí `sources.arq` en config.yaml; si no existe, se usa `sources.dolarapp` (nombre anterior).
    Los mails siguen pudiendo venir de no-reply@dolarapp.com.
    """
    s = cfg.get("sources") or {}
    block = s.get("arq") or s.get("dolarapp")
    return dict(block) if isinstance(block, dict) else {}


def merged_config(project_root: Path) -> dict[str, Any]:
    load_env(project_root)
    yaml_path = project_root / "config.yaml"
    if not yaml_path.is_file():
        yaml_path = project_root / "config.example.yaml"
    cfg = load_yaml_config(yaml_path)
    cfg.setdefault("lookback_days", 30)
    cfg.setdefault("sources", {})
    cfg.setdefault(
        "wallet",
        {"csv_path": "./data/gastos_wallet.csv", "csv_mode": "append"},
    )
    cfg.setdefault("state_db_path", "./data/sync_state.db")
    return cfg

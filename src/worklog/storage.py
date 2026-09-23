"""Lectura/escritura atomica de config.json, state.json y entries/*.json.

Todo bajo ~/.worklog. Escritura atomica: se escribe a un .tmp y se hace
os.replace, para no corromper el archivo si el proceso se corta a la mitad.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime
from pathlib import Path

WORKLOG_DIR = Path.home() / ".worklog"
CONFIG_PATH = WORKLOG_DIR / "config.json"
STATE_PATH = WORKLOG_DIR / "state.json"
ENTRIES_DIR = WORKLOG_DIR / "entries"


def ensure_dirs() -> None:
    ENTRIES_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, data: dict | list) -> None:
    ensure_dirs()
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    os.replace(tmp_path, path)


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict) -> None:
    _atomic_write(CONFIG_PATH, config)


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"active_date": None}
    with STATE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    _atomic_write(STATE_PATH, state)


def get_active_date() -> date:
    state = load_state()
    active_date = state.get("active_date")
    if active_date is None:
        return date.today()
    return datetime.strptime(active_date, "%Y-%m-%d").date()


def set_active_date(target_date: date | None) -> None:
    save_state({"active_date": target_date.isoformat() if target_date else None})


def entries_path(target_date: date) -> Path:
    return ENTRIES_DIR / f"{target_date.isoformat()}.json"


def load_entries(target_date: date) -> list[dict]:
    path = entries_path(target_date)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_entries(target_date: date, entries: list[dict]) -> None:
    _atomic_write(entries_path(target_date), entries)


def add_entry(target_date: date, type_name: str, resolved: dict) -> dict:
    entries = load_entries(target_date)
    entry = {
        "id": uuid.uuid4().hex[:12],
        "type": type_name,
        "duration_seconds": resolved["duration_seconds"],
        "duration_raw": resolved["dur"],
        "ticket": resolved["ticket"],
        "comment": resolved["comment"],
        "init": resolved["init"],
        "date": target_date.isoformat(),
        "created_at": datetime.now().astimezone().isoformat(),
        "pushed": False,
        "jira_worklog_id": None,
    }
    entries.append(entry)
    save_entries(target_date, entries)
    return entry


def remove_entry(target_date: date, entry_id: str) -> bool:
    entries = load_entries(target_date)
    remaining = [e for e in entries if e["id"] != entry_id]
    if len(remaining) == len(entries):
        return False
    save_entries(target_date, remaining)
    return True


def mark_pushed(target_date: date, entry_id: str, jira_worklog_id: str) -> None:
    entries = load_entries(target_date)
    for entry in entries:
        if entry["id"] == entry_id:
            entry["pushed"] = True
            entry["jira_worklog_id"] = jira_worklog_id
            break
    save_entries(target_date, entries)

"""Logica de cada subcomando. cli.py solo parsea argumentos y llama aca."""

from __future__ import annotations

from datetime import date, timedelta

from worklog import storage, validation
from worklog.jira_push import JiraConfigError, push_entry

WORKDAY_SECONDS = 8 * 3600

# Bucket ad-hoc: siempre disponible, no requiere 'type set' previo. Si el
# usuario SI corre 'type set task ...', esos defaults se usan igual (queda
# en config.json como cualquier otro tipo) -- esto solo cubre el caso en
# que todavia no fue configurado.
BUILTIN_ADHOC_TYPE = "task"


def type_list() -> dict:
    return storage.load_config()


def type_set(
    name: str,
    init: str | None = None,
    ticket: str | None = None,
    comment: str | None = None,
    dur: str | None = None,
) -> dict:
    if init is not None:
        init = validation.validate_init(init)
    if ticket is not None:
        ticket = validation.validate_ticket(ticket)
    if dur is not None:
        validation.parse_duration(dur)

    config = storage.load_config()
    existing = config.get(name, {})
    config[name] = {
        "ticket": ticket if ticket is not None else existing.get("ticket"),
        "comment": comment if comment is not None else existing.get("comment"),
        "init": init if init is not None else existing.get("init"),
        "dur": dur if dur is not None else existing.get("dur"),
    }
    storage.save_config(config)
    return config[name]


def type_rm(name: str) -> None:
    config = storage.load_config()
    if name not in config:
        raise ValueError(f"El tipo {name!r} no existe en config.json.")
    del config[name]
    storage.save_config(config)


def record(
    type_name: str,
    *,
    dur: str | None,
    dia: int | None,
    date_str: str | None,
    ticket: str | None,
    comment: str | None,
    init: str | None,
) -> dict:
    if dia is not None and date_str is not None:
        raise ValueError("--dia y --date son mutuamente excluyentes, usa uno solo.")

    config = storage.load_config()
    if type_name not in config:
        if type_name != BUILTIN_ADHOC_TYPE:
            raise ValueError(
                f"Tipo {type_name!r} no configurado. Usar 'worklog type set {type_name} ...' primero."
            )
        type_config = {}
    else:
        type_config = config[type_name]

    active_date = storage.get_active_date()
    target_date = validation.resolve_date(dia, date_str, active_date)
    resolved = validation.resolve_entry_fields(
        type_config, dur=dur, ticket=ticket, comment=comment, init=init
    )
    return storage.add_entry(target_date, type_name, resolved)


def set_active(date_str: str | None) -> date | None:
    if date_str is None:
        storage.set_active_date(None)
        return None
    target_date = validation.validate_date(date_str)
    storage.set_active_date(target_date)
    return target_date


def show_active() -> date:
    return storage.get_active_date()


def list_entries(dia: int | None, date_str: str | None) -> tuple[date, list[dict]]:
    if dia is not None and date_str is not None:
        raise ValueError("--dia y --date son mutuamente excluyentes, usa uno solo.")
    target_date = validation.resolve_date(dia, date_str, storage.get_active_date())
    return target_date, storage.load_entries(target_date)


def gap() -> tuple[date, int]:
    target_date = storage.get_active_date()
    entries = storage.load_entries(target_date)
    total = sum(e["duration_seconds"] for e in entries)
    return target_date, WORKDAY_SECONDS - total


def rm_entry(entry_id: str, date_str: str | None) -> date:
    target_date = validation.validate_date(date_str) if date_str else storage.get_active_date()
    if not storage.remove_entry(target_date, entry_id):
        raise ValueError(f"No existe ninguna entry con id {entry_id!r} en {target_date.isoformat()}.")
    return target_date


def _date_range(date_from: str, date_to: str) -> list[date]:
    start = validation.validate_date(date_from)
    end = validation.validate_date(date_to)
    if end < start:
        raise ValueError(f"--to ({end}) es anterior a --from ({start}).")
    days = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def sum_range(date_from: str, date_to: str) -> int:
    total = 0
    for day in _date_range(date_from, date_to):
        total += sum(e["duration_seconds"] for e in storage.load_entries(day))
    return total


def export_range(date_from: str, date_to: str) -> list[dict]:
    result = []
    for day in _date_range(date_from, date_to):
        result.extend(storage.load_entries(day))
    return result


def push(date_str: str | None) -> tuple[date, list]:
    target_date = validation.validate_date(date_str) if date_str else storage.get_active_date()
    entries = storage.load_entries(target_date)
    pending = [e for e in entries if not e["pushed"]]

    results = []
    for entry in pending:
        try:
            result = push_entry(entry)
        except JiraConfigError:
            raise
        if result.ok:
            storage.mark_pushed(target_date, entry["id"], result.jira_worklog_id)
        results.append(result)
    return target_date, results

"""Validacion de formatos y resolucion de campos antes de guardar un registro.

Regla general: cualquier fallo de formato o de resolucion levanta ValueError
con un mensaje claro. El caller (commands.py) nunca debe atrapar esto para
"seguir de largo" -- si algo no resuelve, no se guarda nada (atomico).
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime

DUR_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?$")
TICKET_RE = re.compile(r"^[A-Z][A-Z0-9]*-\d+$")
INIT_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_duration(dur: str) -> int:
    """Valida y convierte "1h35m" / "38m" / "8h" a segundos. Nunca 0."""
    match = DUR_RE.match(dur.strip())
    if not match or (match.group(1) is None and match.group(2) is None):
        raise ValueError(
            f"--dur invalido: {dur!r}. Formato esperado: '1h35m', '38m' u '8h'."
        )
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = hours * 3600 + minutes * 60
    if seconds == 0:
        raise ValueError(f"--dur no puede ser 0: {dur!r}")
    return seconds


def validate_ticket(ticket: str) -> str:
    ticket = ticket.strip()
    if not TICKET_RE.match(ticket):
        raise ValueError(f"--ticket invalido: {ticket!r}. Formato esperado: 'PROY-123'.")
    return ticket


def validate_init(init: str) -> str:
    init = init.strip()
    match = INIT_RE.match(init)
    if not match:
        raise ValueError(f"--init invalido: {init!r}. Formato esperado: 'HH:MM' (24hs).")
    hour, minute = match.groups()
    return f"{int(hour):02d}:{minute}"


def resolve_date(dia: int | None, date_str: str | None, active_date: date) -> date:
    """Resuelve la fecha del registro a partir de --dia / --date / dia activo.

    --dia y --date son mutuamente excluyentes (se valida en la capa de CLI).
    """
    if date_str is not None:
        return validate_date(date_str)
    if dia is not None:
        return validate_dia(dia, active_date)
    return active_date


def validate_date(date_str: str) -> date:
    date_str = date_str.strip()
    if not DATE_RE.match(date_str):
        raise ValueError(f"--date invalido: {date_str!r}. Formato esperado: 'YYYY-MM-DD'.")
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"--date invalido: {date_str!r}. Fecha inexistente en el calendario.") from exc


def validate_dia(dia: int, active_date: date) -> date:
    if not (1 <= dia <= 31):
        raise ValueError(f"--dia invalido: {dia!r}. Debe estar entre 1 y 31.")
    last_day = calendar.monthrange(active_date.year, active_date.month)[1]
    if dia > last_day:
        raise ValueError(
            f"--dia invalido: {dia!r}. El mes {active_date.month}/{active_date.year} "
            f"tiene {last_day} dias."
        )
    return active_date.replace(day=dia)


def resolve_entry_fields(
    type_config: dict,
    *,
    dur: str | None,
    ticket: str | None,
    comment: str | None,
    init: str | None,
) -> dict:
    """Combina defaults del tipo con overrides de la carga.

    Cada campo (ticket, comment, dur, init) debe terminar con un valor real.
    Si alguno queda sin resolver, levanta ValueError -- el entry NO se genera.
    Guarda `is None` explicito, nunca truthiness (un default "0h0m" ya fue
    rechazado en parse_duration, no hay falsy valido que confundir aca).
    """
    resolved_ticket = ticket if ticket is not None else type_config.get("ticket")
    resolved_comment = comment if comment is not None else type_config.get("comment")
    resolved_dur = dur if dur is not None else type_config.get("dur")
    resolved_init = init if init is not None else type_config.get("init")

    missing = [
        name
        for name, value in (
            ("ticket", resolved_ticket),
            ("comment", resolved_comment),
            ("dur", resolved_dur),
            ("init", resolved_init),
        )
        if value is None
    ]
    if missing:
        raise ValueError(
            "Faltan campos sin default ni override, no se genera el registro: "
            + ", ".join(f"--{name}" for name in missing)
        )

    resolved_ticket = validate_ticket(resolved_ticket)
    resolved_init = validate_init(resolved_init)
    duration_seconds = parse_duration(resolved_dur)

    return {
        "ticket": resolved_ticket,
        "comment": resolved_comment,
        "dur": resolved_dur,
        "init": resolved_init,
        "duration_seconds": duration_seconds,
    }

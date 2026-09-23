"""Entry point del CLI `worklog`. Solo parsea argumentos (Typer) y llama a
commands.py -- ninguna logica de negocio vive aca.

Los subcomandos de "tipo" (worklog daily, worklog task, ...) se registran
dinamicamente al arrancar, leyendo ~/.worklog/config.json.
"""

from __future__ import annotations

import json
from typing import Optional

import typer

from worklog import commands, storage
from worklog.jira_push import JiraConfigError

app = typer.Typer(help="Registro rapido de horas trabajadas, con push a Jira.")
type_app = typer.Typer(help="Gestion de tipos repetitivos (daily, task, mrreviewer, ...).")
app.add_typer(type_app, name="type")


ERROR_COLOR = (209, 154, 102)  # naranja suave (One Dark), legible en temas oscuros


def _fail(message: str) -> None:
    typer.secho(message, fg=ERROR_COLOR, err=True)
    raise typer.Exit(code=1)


def _seconds_to_human(seconds: int) -> str:
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours and minutes:
        return f"{sign}{hours}h{minutes}m"
    if hours:
        return f"{sign}{hours}h"
    return f"{sign}{minutes}m"


def _make_type_command(type_name: str):
    def handler(
        dur: Optional[str] = typer.Option(None, "--dur", help="Duracion, ej: 1h35m, 38m, 8h"),
        dia: Optional[int] = typer.Option(None, "--dia", help="Dia del mes actual (1-31)"),
        date: Optional[str] = typer.Option(None, "--date", help="Fecha completa YYYY-MM-DD"),
        ticket: Optional[str] = typer.Option(None, "--ticket", help="Ticket Jira, ej: I2W-100"),
        comment: Optional[str] = typer.Option(None, "--comment", help="Comentario del worklog"),
        init: Optional[str] = typer.Option(None, "--init", help="Hora de inicio HH:MM (24hs)"),
    ) -> None:
        try:
            entry = commands.record(
                type_name,
                dur=dur,
                dia=dia,
                date_str=date,
                ticket=ticket,
                comment=comment,
                init=init,
            )
        except ValueError as exc:
            _fail(str(exc))
            return
        typer.secho(
            f"Registrado [{entry['id']}] {entry['type']} {entry['duration_raw']} "
            f"{entry['ticket']} @ {entry['init']} el {entry['date']}",
            fg=typer.colors.GREEN,
        )

    if type_name == commands.BUILTIN_ADHOC_TYPE:
        handler.__doc__ = "Registrar horas ad-hoc (bucket generico, sin defaults salvo que lo configures con 'type set')."
    else:
        handler.__doc__ = f"Registrar horas de tipo '{type_name}'."
    return handler


def _register_dynamic_type_commands() -> None:
    type_names = set(storage.load_config()) | {commands.BUILTIN_ADHOC_TYPE}
    for type_name in sorted(type_names):
        app.command(name=type_name)(_make_type_command(type_name))


@app.command(name="set")
def set_cmd(
    date: Optional[str] = typer.Option(None, "--date", help="Fecha a fijar como dia activo"),
    show: bool = typer.Option(False, "--show", help="Solo muestra el dia activo actual"),
) -> None:
    """Fija, limpia o muestra el dia activo (sin --date vuelve a 'hoy')."""
    if show:
        typer.echo(f"Dia activo: {commands.show_active().isoformat()}")
        return
    try:
        target = commands.set_active(date)
    except ValueError as exc:
        _fail(str(exc))
        return
    typer.echo(f"Dia activo -> {target.isoformat() if target else 'hoy'}")


@type_app.command(name="list")
def type_list_cmd() -> None:
    """Lista los tipos configurados y sus defaults."""
    config = commands.type_list()
    if not config:
        typer.echo("No hay tipos configurados. Usa 'worklog type set <nombre> --init HH:MM'.")
        return
    for name, cfg in sorted(config.items()):
        typer.echo(
            f"{name}: ticket={cfg.get('ticket')} comment={cfg.get('comment')!r} "
            f"init={cfg.get('init')} dur={cfg.get('dur')}"
        )


@type_app.command(name="set")
def type_set_cmd(
    name: str = typer.Argument(..., help="Nombre del tipo, ej: daily, task"),
    init: Optional[str] = typer.Option(None, "--init", help="Hora de inicio HH:MM default"),
    ticket: Optional[str] = typer.Option(None, "--ticket", help="Ticket Jira default"),
    comment: Optional[str] = typer.Option(None, "--comment", help="Comentario default"),
    dur: Optional[str] = typer.Option(None, "--dur", help="Duracion default, ej: 15m"),
) -> None:
    """Crea o actualiza un tipo repetitivo. Todos los campos son opcionales."""
    try:
        cfg = commands.type_set(name, init, ticket=ticket, comment=comment, dur=dur)
    except ValueError as exc:
        _fail(str(exc))
        return
    typer.secho(f"Tipo {name!r} guardado: {cfg}", fg=typer.colors.GREEN)


@type_app.command(name="rm")
def type_rm_cmd(name: str = typer.Argument(..., help="Nombre del tipo a borrar")) -> None:
    """Borra un tipo repetitivo de config.json."""
    try:
        commands.type_rm(name)
    except ValueError as exc:
        _fail(str(exc))
        return
    typer.secho(f"Tipo {name!r} borrado.", fg=typer.colors.GREEN)


@app.command(name="list")
def list_cmd(
    dia: Optional[int] = typer.Option(None, "--dia", help="Dia del mes actual (1-31)"),
    date: Optional[str] = typer.Option(None, "--date", help="Fecha completa YYYY-MM-DD"),
) -> None:
    """Lista las entries de un dia, marcando pusheado/pendiente (default: dia activo)."""
    try:
        target_date, entries = commands.list_entries(dia, date)
    except ValueError as exc:
        _fail(str(exc))
        return
    if not entries:
        typer.echo(f"Sin entries para {target_date.isoformat()}.")
        return
    typer.echo(f"Entries de {target_date.isoformat()}:")
    for e in entries:
        if e["pushed"]:
            status = f"pusheado (worklog {e['jira_worklog_id']})"
        else:
            status = "pendiente"
        typer.echo(f"\n[{e['id']}] {e['type']}")
        typer.echo(f"  ticket:  {e['ticket']}")
        typer.echo(f"  dur:     {e['duration_raw']}")
        typer.echo(f"  init:    {e['init']}")
        typer.echo(f"  comment: {e['comment']}")
        typer.echo(f"  estado:  {status}")

    total = sum(e["duration_seconds"] for e in entries)
    typer.echo(f"\nTotal registrado: {_seconds_to_human(total)}")


@app.command(name="gap")
def gap_cmd() -> None:
    """Horas sin registrar hoy (8h - suma cargada del dia activo)."""
    target_date, remaining = commands.gap()
    label = "faltan" if remaining >= 0 else "excedido por"
    typer.echo(f"{target_date.isoformat()}: {label} {_seconds_to_human(remaining)}")


@app.command(name="rm")
def rm_cmd(
    entry_id: str = typer.Argument(..., help="Id de la entry a borrar"),
    date: Optional[str] = typer.Option(None, "--date", help="Fecha de la entry (default: dia activo)"),
) -> None:
    """Borra una entry antes de pushearla."""
    try:
        target_date = commands.rm_entry(entry_id, date)
    except ValueError as exc:
        _fail(str(exc))
        return
    typer.secho(f"Entry {entry_id} borrada de {target_date.isoformat()}.", fg=typer.colors.GREEN)


@app.command(name="sum")
def sum_cmd(
    date_from: str = typer.Option(..., "--from", help="Fecha inicio YYYY-MM-DD"),
    date_to: str = typer.Option(..., "--to", help="Fecha fin YYYY-MM-DD"),
) -> None:
    """Total de horas cargadas en un rango de fechas."""
    try:
        total = commands.sum_range(date_from, date_to)
    except ValueError as exc:
        _fail(str(exc))
        return
    typer.echo(f"Total {date_from} a {date_to}: {_seconds_to_human(total)}")


@app.command(name="export")
def export_cmd(
    date_from: str = typer.Option(..., "--from", help="Fecha inicio YYYY-MM-DD"),
    date_to: str = typer.Option(..., "--to", help="Fecha fin YYYY-MM-DD"),
    out: Optional[str] = typer.Option(None, "--out", help="Archivo de salida (default: stdout)"),
) -> None:
    """Dump crudo de entries en un rango, para pasarselo a otra IA/sesion."""
    try:
        data = commands.export_range(date_from, date_to)
    except ValueError as exc:
        _fail(str(exc))
        return
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(payload + "\n")
        typer.secho(f"Exportado a {out}", fg=typer.colors.GREEN)
    else:
        typer.echo(payload)


@app.command(name="push")
def push_cmd(
    date: Optional[str] = typer.Option(None, "--date", help="Fecha a pushear (default: dia activo)"),
) -> None:
    """Sube a Jira las entries pendientes de un dia."""
    try:
        target_date, results = commands.push(date)
    except ValueError as exc:
        _fail(str(exc))
        return
    except JiraConfigError as exc:
        _fail(f"Error de configuracion de Jira: {exc}")
        return

    if not results:
        typer.echo(f"Nada pendiente de pushear en {target_date.isoformat()}.")
        return

    ok_count = 0
    for result in results:
        if result.ok:
            ok_count += 1
            typer.secho(f"  [{result.entry_id}] OK -> worklog {result.jira_worklog_id}", fg=typer.colors.GREEN)
        else:
            typer.secho(f"  [{result.entry_id}] FALLO -> {result.detail}", fg=typer.colors.RED)

    typer.echo(f"Resumen {target_date.isoformat()}: {ok_count} ok, {len(results) - ok_count} fallaron.")


_register_dynamic_type_commands()


if __name__ == "__main__":
    app()

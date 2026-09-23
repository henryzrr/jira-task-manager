"""Push de entries a Jira via REST, reusando el patron Basic auth ya probado.

Lee ~/bin/.jira.env (JIRA_BASE_URL, JIRA_PAT, JIRA_EMAIL). Nunca hardcodea
credenciales -- si el archivo falta o le faltan variables, falla con un
mensaje que le pide al usuario revisar/editar su .jira.env.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path

JIRA_ENV_PATH = Path.home() / "bin" / ".jira.env"


class JiraConfigError(RuntimeError):
    pass


class JiraPushResult:
    def __init__(self, entry_id: str, ok: bool, detail: str, jira_worklog_id: str | None = None):
        self.entry_id = entry_id
        self.ok = ok
        self.detail = detail
        self.jira_worklog_id = jira_worklog_id


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        raise JiraConfigError(
            f"No existe {path}. Crea el archivo con JIRA_BASE_URL, JIRA_PAT y JIRA_EMAIL."
        )
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _load_jira_config() -> dict[str, str]:
    env = _parse_env_file(JIRA_ENV_PATH)
    required = ["JIRA_BASE_URL", "JIRA_PAT", "JIRA_EMAIL"]
    missing = [key for key in required if not env.get(key)]
    if missing:
        raise JiraConfigError(
            f"Faltan variables en {JIRA_ENV_PATH}: {', '.join(missing)}. Revisa/edita ese archivo."
        )
    return env


def _auth_header(email: str, token: str) -> str:
    raw = f"{email}:{token}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _started_timestamp(entry_date: date, init: str) -> str:
    hour, minute = (int(part) for part in init.split(":"))
    dt = datetime(entry_date.year, entry_date.month, entry_date.day, hour, minute).astimezone()
    offset = dt.strftime("%z")  # ej "-0300"
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000") + offset


def _comment_adf(text: str) -> dict:
    """La API v3 exige el comment en Atlassian Document Format, no texto
    plano -- un string ahi invalida el body entero (400, "worklog no puede
    ser nulo"), no solo el campo comment."""
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def push_entry(entry: dict) -> JiraPushResult:
    """Sube una entry a Jira. No levanta excepcion por fallas de Jira (red,
    404, permisos) -- eso se reporta en el resultado para que el caller
    pueda seguir con las demas entries del lote. Si falta config local
    (.jira.env), eso SI levanta JiraConfigError: no es un error de "esta
    entry", es un error de setup que detiene todo el push.
    """
    config = _load_jira_config()
    base_url = config["JIRA_BASE_URL"].rstrip("/")
    ticket = entry["ticket"]
    started = _started_timestamp(date.fromisoformat(entry["date"]), entry["init"])
    body = json.dumps(
        {
            "started": started,
            "timeSpentSeconds": entry["duration_seconds"],
            "comment": _comment_adf(entry["comment"]),
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        url=f"{base_url}/rest/api/3/issue/{ticket}/worklog",
        data=body,
        method="POST",
        headers={
            "Authorization": _auth_header(config["JIRA_EMAIL"], config["JIRA_PAT"]),
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            if response.status != 201:
                return JiraPushResult(
                    entry["id"], ok=False, detail=f"HTTP {response.status} inesperado"
                )
            payload = json.loads(response.read().decode("utf-8"))
            return JiraPushResult(entry["id"], ok=True, detail="OK", jira_worklog_id=payload["id"])
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return JiraPushResult(entry["id"], ok=False, detail=f"HTTP {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        return JiraPushResult(entry["id"], ok=False, detail=f"Error de red: {exc.reason}")

# worklog

## Que es

CLI personal (no publicado, uso propio) para registrar horas trabajadas en
local, dia a dia, y subirlas a Jira en un solo paso al final del dia. No
automatiza la deteccion de duracion real (calendario/GitLab no la reflejan
bien) — el habito sigue siendo manual, pero rapido de terminal en vez de la
web de Jira.

## Dependencias

- Python >= 3.10 (stdlib para casi todo: `json`, `urllib`, `calendar`, `re`)
- [Typer](https://typer.tiangolo.com/) >= 0.12 — unica dependencia externa,
  da los subcomandos, `--help` anidado y autocompletado de shell.
- Nada mas. Sin base de datos, sin `requests` (el push a Jira usa
  `urllib.request` de la stdlib).

## Estructura del proyecto

```
jira-task-register/
├── src/worklog/
│   ├── cli.py           # Typer app, parseo de argumentos, subcomandos dinamicos por tipo
│   ├── commands.py       # logica de cada comando (independiente de Typer)
│   ├── validation.py     # regex + resolucion de campos (dur/dia/date/init/ticket)
│   ├── storage.py        # lectura/escritura atomica de config/state/entries
│   └── jira_push.py      # push via REST, Basic auth con ~/bin/.jira.env
├── tests/
├── pyproject.toml        # metadata + entry point (worklog = "worklog.cli:app")
└── README.md
```

## Instalacion

```bash
cd ~/bin/jira-task-register
python3 -m venv .venv                  # crea entorno virtual propio del proyecto
.venv/bin/pip install -e .             # instala worklog + Typer DENTRO del venv
                                        # -e = editable: cambios en src/ se reflejan sin reinstalar
```

Esto genera un ejecutable real en `.venv/bin/worklog` (con su propio shebang
apuntando al python del venv, que es el unico que tiene Typer instalado). Ese
binario NO esta en tu PATH todavia — para eso el symlink:

```bash
ln -sf ~/bin/jira-task-register/.venv/bin/worklog ~/bin/worklog
```

`~/bin` ya esta en tu `$PATH`. El symlink es solo un puntero: cuando corres
`worklog` desde cualquier lado, en realidad se ejecuta
`~/bin/jira-task-register/.venv/bin/worklog`. Si mas adelante haces
`git pull`/editas codigo y reinstalas, no hace falta rehacer el symlink (el
binario destino es el mismo path).

Verificar que quedo bien:
```bash
worklog --help
```

### Autocompletado de shell (opcional)

```bash
worklog --install-completion
# reabrir la terminal despues
```

## Donde se guardan los datos

Todo en `~/.worklog/` — **fuera del repo**, no se versiona ni se toca al
reinstalar:

```
~/.worklog/
├── config.json           # tipos repetitivos (daily, task, mrreviewer, ...)
├── state.json             # dia activo (worklog set)
└── entries/
    ├── 2026-09-23.json    # registros de ESE dia
    └── 2026-09-07.json
```

Se crea solo, la primera vez que corres algo que necesite escribir ahi
(`worklog type set` o `worklog <tipo>`).

## Tipos: `task` vs tipos con defaults

- **`task`** — bucket generico ad-hoc, **siempre disponible**, sin `type set`
  previo. Como no tiene defaults, exige `--dur --ticket --comment --init`
  completos en cada carga.
- **Cualquier otro nombre** (`daily`, `mrreviewer`, el que definas) — necesita
  `worklog type set <nombre> [--init HH:MM] [...]` una vez, para guardar los
  defaults que despues te ahorran retipear. Todos los campos son opcionales
  en `type set`; lo que no definas ahi lo vas a tener que pasar a mano en
  cada carga (o falla explicito si falta).

## Uso rapido

```bash
# 1. definir tipos repetitivos (todos los campos son opcionales)
#    "task" es la unica excepcion: existe siempre, no hace falta configurarlo.
worklog type set daily --init 09:50 --ticket I2W-100 --comment "Daily sprint planning" --dur 15m
worklog type list                                # ver que hay configurado
worklog type rm daily                            # borrar un tipo

# 2. cargar horas (el tipo es un subcomando, no un flag)
worklog daily                                    # usa todos los defaults del tipo
worklog task --dur 5h --dia 7 --ticket I2W-33 --comment "se trabajo en..."  # sin setup previo
worklog daily --dur 20m --ticket I2W-444         # override puntual de un default

# 3. dia activo (todo lo que cargues despues apunta ahi, sin repetir --dia/--date)
worklog set --date 2026-09-14
worklog set --show                               # solo muestra, no modifica nada
worklog set                                       # limpia -> vuelve a "hoy"

# 4. consulta y control
worklog list                                     # entries del dia activo
worklog list --date 2026-09-14                   # entries de un dia puntual
worklog gap                                      # horas sin registrar hoy (8h - cargado)
worklog rm <entry_id>                            # borra una entry mal cargada, antes de pushear
worklog edit <entry_id> --dur 2h --comment "..." # edita solo los campos pasados, antes de pushear
worklog sum --from 2026-09-01 --to 2026-09-18
worklog export --from 2026-09-01 --to 2026-09-18 --out export.json

# 5. subir a Jira
worklog push                                     # entries pendientes del dia activo
worklog push --date 2026-09-14
```

Ayuda en cualquier nivel: `worklog --help`, `worklog type --help`,
`worklog type set --help`, `worklog sum --help`, etc.

## Validacion

Antes de guardar cualquier entry se valida formato de `--dur` (`1h35m`,
`38m`, `8h`), `--dia` (1-31, valido para el mes activo), `--date`
(`YYYY-MM-DD` real), `--init` (`HH:MM` 24hs) y `--ticket` (`PROY-123`,
prefijo alfanumerico tipo `I2W-100`). Ademas se resuelven los 4 campos del
tipo (`ticket`, `comment`, `dur`, `init`) combinando default + override; si
falta alguno, el CLI **no guarda nada** — imprime el error y listo
(operacion atomica, todo o nada).

`--init` nunca cae a "la hora actual del sistema": si el tipo no tiene un
`init` default y no pasaste `--init` en la carga, es error explicito
(evita horas erroneas al backfillear un dia pasado).

## Jira (push)

`push` lee `~/bin/.jira.env` (`JIRA_BASE_URL`, `JIRA_PAT`, `JIRA_EMAIL`) y
autentica con Basic auth (`base64(email:token)`). Si el archivo falta o le
faltan variables, `push` falla con un mensaje pidiendo revisar/editar ese
archivo — el CLI nunca genera, guarda ni hardcodea credenciales propias.

Por cada entry pendiente (`pushed: false`) hace
`POST {JIRA_BASE_URL}/rest/api/3/issue/{ticket}/worklog`. Si Jira responde
201, marca la entry como `pushed: true` y guarda el `jira_worklog_id`; si
falla, sigue con las demas del lote y al final imprime un resumen
ok/fallidas. Una entry ya pusheada nunca se reintenta sola.

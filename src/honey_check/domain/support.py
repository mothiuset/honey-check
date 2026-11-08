"""Contrato de las herramientas de soporte: definición, plan, resultado y registro de ejecución.

Una herramienta declara qué pide y cuánto riesgo tiene; antes de actuar presenta un plan con los
comandos equivalentes; al terminar devuelve un resultado estructurado que la interfaz sabe
mostrar sin conocer la herramienta (resumen, verificaciones, tablas con acciones, gráficos).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from .observed import Model


class Risk(StrEnum):
    READ = "read"  # solo consulta
    CHANGE = "change"  # modifica algo recuperable (servicio, caché, configuración con respaldo)
    DESTRUCTIVE = "destructive"  # elimina o desinstala: requiere confirmación explícita


class ParamKind(StrEnum):
    TEXT = "text"
    PATH = "path"
    NUMBER = "number"
    BOOL = "bool"
    CHOICE = "choice"
    MULTI = "multi"  # varios valores (selección en una tabla)
    SECRET = "secret"  # noqa: S105 - tipo de parámetro: se usa y se descarta, nunca se registra


class Choice(Model):
    value: str
    label: str
    # Opciones en vivo (particiones de un disco): grupo, detalle, uso y por qué no se puede elegir.
    group: str | None = None
    detail: str | None = None
    used: float | None = None  # fracción ocupada, para la barra
    disabled_reason: str | None = None


class Param(Model):
    name: str
    label: str
    kind: ParamKind = ParamKind.TEXT
    required: bool = False
    default: Any = None
    help: str | None = None
    choices: list[Choice] = Field(default_factory=list)
    pattern: str | None = None  # expresión regular que el valor debe cumplir completo
    max_length: int = 512
    # Opciones que se leen del equipo al abrir la herramienta (GET /api/support/sources/<nombre>).
    source: str | None = None
    # Una ruta que se elige con el diálogo de Windows: «folder», o «file» con sus tipos
    # («Controladores (*.inf)|*.inf»).
    browse: str | None = None
    browse_filter: str | None = None


class ToolDefinition(Model):
    id: str
    category: str
    title: str
    description: str
    risk: Risk
    requires_admin: bool = False
    params: list[Param] = Field(default_factory=list)
    # Herramienta que solo se usa desde otra (acción de una fila): no se lista en el catálogo.
    hidden: bool = False
    contacts_network: bool = False  # habla con otro equipo de la red (impresora, controlador)
    # Texto del botón cuando el título describe un problema («Las directivas no se aplican»).
    action_label: str | None = None
    # Se ejecuta con el clic donde esté el técnico, sin pantalla ni revisión: abrir una
    # carpeta, vaciar la caché DNS. Solo para lo que no tiene nada que revisar ni deshacer.
    instant: bool = False


class PlanStep(Model):
    title: str
    command: str | None = None  # comando equivalente que el técnico podría ejecutar a mano
    detail: str | None = None


class Plan(Model):
    """Lo que se hará, tal como el técnico lo confirma. `requires_admin` sale de la revisión
    previa: una carpeta en Program Files lo exige aunque la herramienta no siempre lo necesite."""

    id: str
    tool: str
    title: str
    risk: Risk
    requires_admin: bool
    params: dict[str, Any]
    steps: list[PlanStep]
    action_label: str | None = None
    # Una frase con lo que va a pasar, para el botón y la confirmación.
    summary: str | None = None
    # Revisión previa: qué existe, qué está en uso, qué necesita permisos.
    checks: list[Check] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    backup: str | None = None
    created_at: datetime


# --- Resultado ------------------------------------------------------------------------------------


class Tone(StrEnum):
    NEUTRAL = "neutral"
    OK = "ok"
    WARN = "warn"
    BAD = "bad"


class Fact(Model):
    label: str
    value: str | None
    tone: Tone = Tone.NEUTRAL


class CheckStatus(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    INFO = "info"
    SKIPPED = "skipped"


class ActionLink(Model):
    """Otra herramienta que se ofrece desde un resultado; `{campo}` se reemplaza por la fila."""

    tool: str
    label: str
    params: dict[str, str] = Field(default_factory=dict)
    tone: Tone = Tone.NEUTRAL


class Check(Model):
    label: str
    status: CheckStatus
    # Qué pasó y qué hacer, en palabras del técnico.
    detail: str | None = None
    fix: ActionLink | None = None
    # Código y texto de Windows: se muestra solo en «Detalles técnicos».
    technical: str | None = None


class ColumnKind(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    BYTES = "bytes"
    DATE = "date"
    BOOL = "bool"
    PATH = "path"


class Column(Model):
    key: str
    label: str
    kind: ColumnKind = ColumnKind.TEXT
    priority: int = 1


class Table(Model):
    id: str
    title: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    row_key: str
    row_actions: list[ActionLink] = Field(default_factory=list)
    # Acción sobre varias filas: recibe la lista de `row_key` seleccionadas en `selection_param`.
    bulk_action: ActionLink | None = None
    selection_param: str | None = None
    truncated: bool = False


class ChartKind(StrEnum):
    TREEMAP = "treemap"
    BAR = "bar"


class Chart(Model):
    id: str
    title: str
    kind: ChartKind
    data: list[dict[str, Any]]
    unit: str = "bytes"


class FileRef(Model):
    label: str
    path: str


class ToolResult(Model):
    summary: list[Fact] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    charts: list[Chart] = Field(default_factory=list)
    files: list[FileRef] = Field(default_factory=list)
    text: str | None = None
    # Lo que la verificación posterior encontró: el técnico sabe si el cambio surtió efecto.
    verified: bool | None = None


# --- Ejecución ------------------------------------------------------------------------------------


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"  # terminó, pero algún paso no pudo hacerse
    FAILED = "failed"
    CANCELLED = "cancelled"


class LogLevel(StrEnum):
    INFO = "info"
    COMMAND = "command"
    OUTPUT = "output"
    WARN = "warn"
    ERROR = "error"


class LogEntry(Model):
    at: datetime
    level: LogLevel
    text: str


class Progress(Model):
    done: int = 0
    total: int = 0
    label: str | None = None


class Run(Model):
    id: str
    plan_id: str
    tool: str
    title: str
    risk: Risk
    params: dict[str, Any]
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    progress: Progress = Field(default_factory=Progress)
    log: list[LogEntry] = Field(default_factory=list)
    result: ToolResult | None = None
    error: str | None = None
    elevated: bool | None = None
    # Huella del estado que leyó una consulta (programas registrados, espacio libre): si
    # cambia, el resultado quedó atrás y la interfaz ofrece actualizarlo.
    fingerprint: str | None = None


Plan.model_rebuild()

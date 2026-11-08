"""Lo que las herramientas de soporte necesitan del sistema, sin conocer cómo se implementa."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from honey_check.application.ports import CancelToken
from honey_check.domain.inventory import Inventory
from honey_check.domain.support import Check, LogLevel, PlanStep, Run, ToolDefinition, ToolResult


@dataclass(frozen=True)
class CommandOutput:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def text(self) -> str:
        return (self.stdout + ("\n" + self.stderr if self.stderr.strip() else "")).strip()


class CommandFailed(Exception):
    def __init__(self, message: str, output: CommandOutput | None = None) -> None:
        super().__init__(message)
        self.output = output


class CommandRunner(Protocol):
    """Ejecuta un programa del sistema con argumentos como lista (nunca a través de un shell)."""

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_s: float,
        cancel: CancelToken,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> CommandOutput: ...


class RunJournal(Protocol):
    """Registro de ejecuciones en la carpeta de datos."""

    def save(self, run: Run) -> None: ...

    def recent(self, limit: int, tool: str | None = None) -> list[Run]:
        """Versiones livianas (sin tablas ni gráficos), más recientes primero."""
        ...

    def load(self, run_id: str) -> Run | None:
        """Una versión completa, con su resultado."""
        ...


@dataclass(frozen=True)
class UserSession:
    """El usuario que tiene abierta la sesión. Con credenciales de otro administrador en el aviso
    UAC, el proceso elevado es otro usuario: HKCU y AppData se toman de aquí, nunca del proceso."""

    sid: str
    profile: str
    appdata: str
    local_appdata: str
    desktop: str


@dataclass(frozen=True)
class SupportEnvironment:
    data_root: Path
    runner: CommandRunner
    is_elevated: bool | None
    # Último inventario de este equipo, para herramientas que parten de él (desinstalar, tamaños).
    inventory: Inventory | None
    user: UserSession | None = None


class ToolContext(Protocol):
    """Lo que una herramienta puede hacer mientras se ejecuta."""

    env: SupportEnvironment
    cancel: CancelToken

    def info(self, text: str) -> None: ...

    def warn(self, text: str) -> None: ...

    def error(self, text: str) -> None: ...

    def progress(self, done: int, total: int, label: str | None = None) -> None: ...

    def command(
        self,
        args: Sequence[str],
        *,
        timeout_s: float = 120.0,
        stdin: str | None = None,
        quiet: bool = False,
        on_output: Callable[[str], None] | None = None,
    ) -> CommandOutput: ...

    def backup_path(self, name: str) -> Path: ...

    def output_path(self, name: str) -> Path: ...


@dataclass(frozen=True)
class Preparation:
    """Lo que una herramienta sabe antes de actuar: pasos, revisión previa y permisos."""

    steps: list[PlanStep]
    warnings: list[str] = field(default_factory=list)
    backup: str | None = None
    # Una frase con lo que va a pasar («Se enviarán 2 carpetas a la Papelera»).
    summary: str | None = None
    checks: list[Check] = field(default_factory=list)
    # Algo concreto de esta ejecución exige administrador aunque la herramienta no siempre.
    needs_admin: bool = False


class Tool(Protocol):
    definition: ToolDefinition

    def plan(self, params: Mapping[str, Any], env: SupportEnvironment) -> Preparation: ...

    def execute(self, params: Mapping[str, Any], ctx: ToolContext) -> ToolResult: ...


class RunRecorder(Protocol):
    """El registro de una ejecución, para reenviar lo que otro proceso escribe."""

    cancel: CancelToken

    def record(self, level: LogLevel, text: str) -> None: ...

    def progress(self, done: int, total: int, label: str | None = None) -> None: ...


class ElevationDeclined(PermissionError):
    """El técnico cerró o rechazó el aviso de administrador: no cambió nada."""


class ElevatedExecutor(Protocol):
    """Ejecuta una herramienta en un proceso aparte con permisos de administrador (aviso UAC);
    el registro y el avance llegan en vivo y devuelve el resultado como si corriera aquí."""

    def execute(
        self,
        tool_id: str,
        params: Mapping[str, Any],
        env: SupportEnvironment,
        recorder: RunRecorder,
    ) -> ToolResult: ...

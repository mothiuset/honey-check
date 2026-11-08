"""Contexto de una ejecución: registro, avance, comandos con su eco y rutas de respaldo."""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from honey_check.application.ports import CancelToken, CollectionCancelled
from honey_check.domain.support import LogEntry, LogLevel, Progress

from .ports import CommandOutput, SupportEnvironment, ToolContext

_MAX_LOG = 2000
_MAX_OUTPUT_CHARS = 4000
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_name(text: str) -> str:
    return _SAFE_NAME.sub("_", text).strip(" .")[:80] or "archivo"


def quote(argument: str) -> str:
    return f'"{argument}"' if (" " in argument or not argument) else argument


def command_line(args: Sequence[str]) -> str:
    return " ".join(quote(str(a)) for a in args)


class RunContext:
    def __init__(
        self,
        env: SupportEnvironment,
        cancel: CancelToken,
        run_id: str,
        on_change: Callable[[], None],
        secrets: Sequence[str] = (),
    ) -> None:
        self.env = env
        self.cancel = cancel
        self._run_id = run_id
        self._on_change = on_change
        self._lock = threading.Lock()
        self._secrets = [s for s in secrets if s]
        self.log: list[LogEntry] = []
        self.progress_state = Progress()

    def _redact(self, text: str) -> str:
        for secret in self._secrets:
            text = text.replace(secret, "••••")
        return text

    def record(self, level: LogLevel, text: str) -> None:
        """Entrada que llega de otro proceso (la ejecución como administrador)."""
        self._add(level, text)

    def _add(self, level: LogLevel, text: str) -> None:
        with self._lock:
            if len(self.log) < _MAX_LOG:
                self.log.append(
                    LogEntry(at=datetime.now(UTC), level=level, text=self._redact(text))
                )
        self._on_change()

    def info(self, text: str) -> None:
        self._add(LogLevel.INFO, text)

    def warn(self, text: str) -> None:
        self._add(LogLevel.WARN, text)

    def error(self, text: str) -> None:
        self._add(LogLevel.ERROR, text)

    def progress(self, done: int, total: int, label: str | None = None) -> None:
        self.progress_state = Progress(done=done, total=total, label=label)
        self._on_change()

    def command(
        self,
        args: Sequence[str],
        *,
        timeout_s: float = 120.0,
        stdin: str | None = None,
        quiet: bool = False,
        on_output: Callable[[str], None] | None = None,
    ) -> CommandOutput:
        """`on_output` recibe la salida en vivo (para mostrar el avance de comandos largos)."""
        self.cancel.raise_if_cancelled()
        self._add(LogLevel.COMMAND, command_line(args))
        runner = self.env.runner
        if on_output:
            output = runner.run(
                args, timeout_s=timeout_s, cancel=self.cancel, stdin=stdin, on_output=on_output
            )
        else:
            # Sin avance en vivo no se pasa el parámetro: los ejecutores simulados no lo necesitan.
            output = runner.run(args, timeout_s=timeout_s, cancel=self.cancel, stdin=stdin)
        if not quiet and output.text:
            text = output.text
            if len(text) > _MAX_OUTPUT_CHARS:
                text = text[:_MAX_OUTPUT_CHARS] + "\n…"
            self._add(LogLevel.OUTPUT, text)
        if output.exit_code != 0:
            self._add(LogLevel.WARN, f"Código de salida {output.exit_code}")
        return output

    def _folder(self, name: str) -> Path:
        folder = (
            self.env.data_root / name / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}_{self._run_id[:8]}"
        )
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def backup_path(self, name: str) -> Path:
        """Respaldo de lo que se va a cambiar, en HoneyCheck-datos\\respaldos."""
        return self._folder("respaldos") / safe_name(name)

    def output_path(self, name: str) -> Path:
        """Archivos que genera una herramienta (informes, exportaciones)."""
        return self._folder("salidas") / safe_name(name)


class Attempt:
    """Una vía para lograr un paso; `run` devuelve True si lo logró."""

    def __init__(self, label: str, run: Callable[[], bool]) -> None:
        self.label = label
        self.run = run


def first_that_works(ctx: ToolContext, attempts: Sequence[Attempt]) -> str | None:
    """Prueba cada vía en orden hasta que una funcione; devuelve cuál, o None si ninguna."""
    for attempt in attempts:
        ctx.cancel.raise_if_cancelled()
        try:
            if attempt.run():
                ctx.info(f"Hecho mediante: {attempt.label}")
                return attempt.label
            ctx.warn(f"No funcionó: {attempt.label}; se prueba la siguiente vía")
        except CollectionCancelled:
            raise
        except Exception as error:  # noqa: BLE001 - cualquier fallo de una vía da paso a la siguiente
            reason = error or type(error).__name__
            ctx.warn(f"No disponible: {attempt.label} ({reason}); se prueba la siguiente vía")
    return None

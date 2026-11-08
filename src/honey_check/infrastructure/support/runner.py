"""Ejecución de herramientas de Windows para el soporte, con salida legible en cualquier idioma."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from honey_check.application.ports import CancelToken
from honey_check.application.support.ports import CommandFailed, CommandOutput
from honey_check.infrastructure.windows.process import (
    OutputTooLarge,
    ProcessRunner,
    ProcessTimeout,
    system32_path,
)


def decode(data: bytes) -> str:
    """Las herramientas de consola escriben en la página OEM (cp850) o, algunas, en UTF-16."""
    if not data:
        return ""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")) or data[1:200:2].count(0) > 40:
        return data.decode("utf-16-le", errors="replace").lstrip("\ufeff")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("oem", errors="replace")


def tool_path(*parts: str) -> str:
    """Programas de Windows siempre desde System32, nunca desde el PATH ni la carpeta actual."""
    return str(system32_path(*parts))


class SystemCommandRunner:
    """Implementa CommandRunner sobre el ProcessRunner con Job (sin huérfanos al salir)."""

    def __init__(self, runner: ProcessRunner) -> None:
        self._runner = runner
        self._cwd = Path(os.environ.get("SYSTEMROOT") or r"C:\Windows") / "System32"

    def run(
        self,
        args: Sequence[str],
        *,
        timeout_s: float,
        cancel: CancelToken,
        stdin: str | None = None,
        env: Mapping[str, str] | None = None,
        on_output: Callable[[str], None] | None = None,
    ) -> CommandOutput:
        environment = dict(os.environ)
        live = (lambda chunk: on_output(decode(chunk))) if on_output else None
        if env:
            environment.update(env)
        try:
            result = self._runner.run(
                [str(a) for a in args],
                stdin=(stdin or "").encode("utf-8"),
                timeout_s=timeout_s,
                cancel=cancel,
                cwd=self._cwd,
                env=environment,
                on_output=live,
            )
        except ProcessTimeout as error:
            raise CommandFailed(
                f"Sin respuesta en {int(timeout_s)} s: {Path(args[0]).name}"
            ) from error
        except OutputTooLarge as error:
            raise CommandFailed("La salida del comando es demasiado grande") from error
        return CommandOutput(result.returncode, decode(result.stdout), decode(result.stderr))

"""Rutas de ejecución, logs diagnósticos y vigilancia de la carpeta de trabajo."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_LOG_BYTES = 1024 * 1024
_LOG_BACKUPS = 2
_MONITOR_SECONDS = 3.0


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def executable_directory() -> Path:
    """Carpeta real del ejecutable, sin letras de unidad fijas ni rutas de desarrollo."""
    # Sin resolver enlaces: en una unidad montada, la letra visible es la ruta correcta.
    if is_frozen():
        return Path(os.path.abspath(sys.executable)).parent  # noqa: PTH100
    return Path.cwd()


def leave_working_directory() -> None:
    """Un directorio actual en la USB impide expulsarla y facilita cargar DLL ajenas."""
    system_root = os.environ.get("SYSTEMROOT")
    if system_root:
        try:
            os.chdir(system_root)
        except OSError:
            log.warning("No se pudo cambiar el directorio de trabajo")


class _SafeRotatingHandler(logging.handlers.RotatingFileHandler):
    """Si la USB desaparece, escribir un log nunca debe interrumpir la aplicación."""

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 - API de logging
        return

    def emit(self, record: logging.LogRecord) -> None:
        try:
            super().emit(record)
        except Exception:  # noqa: BLE001 - nunca se propaga un fallo del log
            return


class _RedactingFormatter(logging.Formatter):
    """Los logs no deben revelar el perfil de usuario ni el nombre del equipo."""

    def __init__(self, fmt: str) -> None:
        super().__init__(fmt)
        secrets = [os.environ.get("USERPROFILE"), os.environ.get("COMPUTERNAME")]
        self._replacements = [value for value in secrets if value]

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for value in self._replacements:
            text = text.replace(value, "<redactado>")
        return text


@dataclass(frozen=True)
class LogSetup:
    directory: Path | None
    fallback_used: bool


def configure_logging(preferred_directory: Path) -> LogSetup:
    """En la carpeta de datos configurada; si no permite escribir, solo en memoria."""
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = "%(asctime)s %(levelname)s %(name)s [%(threadName)s] %(message)s"
    candidates = [(preferred_directory / "logs", False)]
    for directory, is_fallback in candidates:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            handler = _SafeRotatingHandler(
                directory / "honey-check.log",
                maxBytes=_LOG_BYTES,
                backupCount=_LOG_BACKUPS,
                encoding="utf-8",
            )
        except OSError:
            continue
        handler.setFormatter(_RedactingFormatter(fmt))
        root.addHandler(handler)
        return LogSetup(directory, is_fallback)
    root.addHandler(logging.NullHandler())
    return LogSetup(None, True)


class WorkspaceMonitor:
    """Detecta si la carpeta deja de estar disponible, p. ej. al extraer la USB.

    Solo informa: tras una extracción física Windows puede dejar el proceso en un estado que
    Honey Check no controla, por lo que no se promete un cierre ordenado en ese caso.
    """

    def __init__(
        self,
        directory: Callable[[], Path],
        on_change: Callable[[bool], None],
        interval_s: float = _MONITOR_SECONDS,
    ) -> None:
        self._directory = directory
        self._on_change = on_change
        self._interval = interval_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._available = True

    @property
    def available(self) -> bool:
        return self._available

    def check_once(self) -> None:
        try:
            available = self._directory().is_dir()
        except OSError:
            available = False
        if available != self._available:
            self._available = available
            log.warning("Carpeta de trabajo %s", "disponible" if available else "no disponible")
            self._on_change(available)

    def start(self) -> None:
        def loop() -> None:
            while not self._stop.wait(self._interval):
                self.check_once()

        self._thread = threading.Thread(target=loop, name="workspace-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)

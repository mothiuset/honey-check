"""Ejecución acotada de subprocesos: límite de tiempo y de salida, cancelación real y cierre."""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
import subprocess
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

from honey_check.application.ports import CancelToken, CollectionCancelled

log = logging.getLogger(__name__)

_CREATE_NO_WINDOW = 0x08000000
_BELOW_NORMAL_PRIORITY = 0x00004000
_MAX_OUTPUT_BYTES = 64 * 1024 * 1024
_POLL_SECONDS = 0.05


class ProcessTimeout(Exception):
    pass


class OutputTooLarge(Exception):
    pass


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class _JobObject:
    """Job de Windows con «matar al cerrar»: si Honey Check muere, no quedan hijos huérfanos."""

    _KILL_ON_JOB_CLOSE = 0x2000
    _EXTENDED_LIMIT_INFORMATION = 9

    class _BasicLimits(ctypes.Structure):
        _fields_ = (
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        )

    class _IoCounters(ctypes.Structure):
        _fields_ = tuple((name, ctypes.c_uint64) for name in "abcdef")

    class _ExtendedLimits(ctypes.Structure):
        pass

    _ExtendedLimits._fields_ = (
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    )

    def __init__(self) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
        kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel32.SetInformationJobObject.argtypes = (
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        )
        self._kernel32 = kernel32
        self._handle = kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = self._ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = self._KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(
            self._handle,
            self._EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        handle = wintypes.HANDLE(int(process._handle))  # type: ignore[attr-defined]
        if not self._kernel32.AssignProcessToJobObject(self._handle, handle):
            raise ctypes.WinError(ctypes.get_last_error())


class ProcessRunner:
    """Lanza procesos sin consola, con prioridad baja y siempre controlados hasta su fin."""

    def __init__(self, max_output_bytes: int = _MAX_OUTPUT_BYTES) -> None:
        self._max_output = max_output_bytes
        self._active: set[subprocess.Popen[bytes]] = set()
        self._lock = threading.Lock()
        self._closed = False
        try:
            self._job: _JobObject | None = _JobObject()
        except OSError as error:
            # Sin el Job se sigue funcionando: los límites de tiempo no dependen de él.
            log.warning("No se pudo crear el Job de Windows: %s", type(error).__name__)
            self._job = None

    def run(
        self,
        args: list[str],
        *,
        stdin: bytes = b"",
        timeout_s: float,
        cancel: CancelToken,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        on_output: Callable[[bytes], None] | None = None,
    ) -> ProcessResult:
        """`on_output` recibe cada trozo de la salida estándar apenas llega (avance de DISM o
        SFC); sin él, la salida solo se lee al final, como siempre."""
        cancel.raise_if_cancelled()
        with self._lock:
            if self._closed:
                raise CollectionCancelled
            process = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
                creationflags=_CREATE_NO_WINDOW | _BELOW_NORMAL_PRIORITY,
                close_fds=True,
            )
            self._active.add(process)
        try:
            if self._job is not None:
                try:
                    self._job.assign(process)
                except OSError as error:
                    log.debug("Proceso fuera del Job: %s", type(error).__name__)
            return self._supervise(process, stdin, timeout_s, cancel, on_output)
        finally:
            self._terminate(process)
            with self._lock:
                self._active.discard(process)

    def close(self) -> None:
        """Detiene los procesos en curso; las siguientes llamadas se rechazan."""
        with self._lock:
            self._closed = True
            active = list(self._active)
        for process in active:
            self._terminate(process)

    def _supervise(
        self,
        process: subprocess.Popen[bytes],
        stdin: bytes,
        timeout_s: float,
        cancel: CancelToken,
        on_output: Callable[[bytes], None] | None = None,
    ) -> ProcessResult:
        stdout = bytearray()
        stderr = bytearray()
        exceeded = threading.Event()

        def read(stream: object, sink: bytearray, live: Callable[[bytes], None] | None) -> None:
            # read1 devuelve lo que ya llegó: el avance se ve mientras el comando corre.
            reader = stream.read1 if live else stream.read  # type: ignore[attr-defined]
            while chunk := reader(65536):
                if len(sink) + len(chunk) > self._max_output:
                    exceeded.set()
                    return
                sink.extend(chunk)
                if live:
                    with contextlib.suppress(Exception):  # el avance nunca rompe el comando
                        live(chunk)

        def write() -> None:
            try:
                assert process.stdin is not None  # noqa: S101
                process.stdin.write(stdin)
                process.stdin.close()
            except OSError:
                pass  # El proceso terminó antes de leer; su código de salida lo refleja.

        threads = [
            threading.Thread(target=read, args=(process.stdout, stdout, on_output), daemon=True),
            threading.Thread(target=read, args=(process.stderr, stderr, None), daemon=True),
            threading.Thread(target=write, daemon=True),
        ]
        for thread in threads:
            thread.start()

        deadline = time.monotonic() + timeout_s
        while process.poll() is None:
            if exceeded.is_set():
                raise OutputTooLarge
            if cancel.cancelled:
                raise CollectionCancelled
            if time.monotonic() >= deadline:
                raise ProcessTimeout
            time.sleep(_POLL_SECONDS)
        for thread in threads:
            thread.join(2)
        if exceeded.is_set():
            raise OutputTooLarge
        return ProcessResult(process.returncode, bytes(stdout), bytes(stderr))

    @staticmethod
    def _terminate(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            with contextlib.suppress(OSError):
                process.kill()
            try:
                process.wait(3)
            except subprocess.TimeoutExpired:
                log.warning("Un subproceso no terminó tras la orden de cierre")


def system32_path(*parts: str) -> Path:
    """Ruta absoluta bajo System32: nunca se resuelve por PATH ni desde la carpeta de la USB."""
    root = os.environ.get("SYSTEMROOT") or r"C:\Windows"
    return Path(root, "System32", *parts)

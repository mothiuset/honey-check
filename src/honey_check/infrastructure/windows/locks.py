"""Qué procesos tienen en uso unos archivos, y cerrarlos, con el Restart Manager de Windows.

Es la misma API que usan los instaladores para decir «cierre estos programas»: no adivina por el
nombre del proceso, pregunta a Windows quién tiene cada archivo abierto o cargado.
"""

from __future__ import annotations

import ctypes
import os
from collections.abc import Iterable, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

_CCH_RM_SESSION_KEY = 32
_CCH_RM_MAX_APP_NAME = 255
_CCH_RM_MAX_SVC_NAME = 63
_ERROR_MORE_DATA = 234
_RM_FORCE_SHUTDOWN = 0x1
# Primero los binarios: son los que un proceso carga. Un límite evita registrar miles de archivos.
_BINARY = {".exe", ".dll", ".sys", ".ocx", ".node", ".pyd"}
MAX_FILES = 1500


class _UniqueProcess(ctypes.Structure):
    _fields_ = (("dwProcessId", wintypes.DWORD), ("ProcessStartTime", wintypes.FILETIME))


class _ProcessInfo(ctypes.Structure):
    _fields_ = (
        ("Process", _UniqueProcess),
        ("strAppName", wintypes.WCHAR * (_CCH_RM_MAX_APP_NAME + 1)),
        ("strServiceShortName", wintypes.WCHAR * (_CCH_RM_MAX_SVC_NAME + 1)),
        ("ApplicationType", ctypes.c_int),
        ("AppStatus", wintypes.ULONG),
        ("TSSessionId", wintypes.DWORD),
        ("bRestartable", wintypes.BOOL),
    )


_rstrtmgr = ctypes.WinDLL("rstrtmgr", use_last_error=True)
_rstrtmgr.RmStartSession.argtypes = (
    ctypes.POINTER(wintypes.DWORD),
    wintypes.DWORD,
    wintypes.LPWSTR,
)
_rstrtmgr.RmRegisterResources.argtypes = (
    wintypes.DWORD,
    wintypes.UINT,
    ctypes.POINTER(wintypes.LPCWSTR),
    wintypes.UINT,
    wintypes.LPVOID,
    wintypes.UINT,
    wintypes.LPVOID,
)
_rstrtmgr.RmGetList.argtypes = (
    wintypes.DWORD,
    ctypes.POINTER(wintypes.UINT),
    ctypes.POINTER(wintypes.UINT),
    ctypes.POINTER(_ProcessInfo),
    ctypes.POINTER(wintypes.DWORD),
)
_rstrtmgr.RmShutdown.argtypes = (wintypes.DWORD, wintypes.ULONG, wintypes.LPVOID)
_rstrtmgr.RmEndSession.argtypes = (wintypes.DWORD,)

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE, *(ctypes.POINTER(wintypes.FILETIME),) * 4)
_kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
_kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_PROCESS_TERMINATE = 0x0001
_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# RM_APP_TYPE: 3 = servicio, 4 = Explorador, 5 = consola, 1000 = crítico (solo se libera
# reiniciando).
_SERVICE = 3
_CONSOLE = 5
_CRITICAL = 1000


@dataclass(frozen=True)
class LockingProcess:
    pid: int
    name: str
    service: str | None
    critical: bool
    # Hora de inicio (FILETIME): con el PID identifica el proceso aunque el PID se reutilice.
    started: int = 0
    # De consola: no atiende el aviso de cierre de Windows, se termina directamente.
    console: bool = False

    @property
    def label(self) -> str:
        if self.service:
            return f"servicio {self.service}"
        return self.name or f"proceso {self.pid}"


class _Session:
    def __init__(self, files: Sequence[str]) -> None:
        self.handle = wintypes.DWORD()
        key = ctypes.create_unicode_buffer(_CCH_RM_SESSION_KEY + 1)
        code = _rstrtmgr.RmStartSession(ctypes.byref(self.handle), 0, key)
        if code:
            raise ctypes.WinError(code)
        array = (wintypes.LPCWSTR * len(files))(*files)
        code = _rstrtmgr.RmRegisterResources(self.handle, len(files), array, 0, None, 0, None)
        if code:
            self.close()
            raise ctypes.WinError(code)

    def processes(self) -> list[LockingProcess]:
        needed = wintypes.UINT()
        count = wintypes.UINT(0)
        reasons = wintypes.DWORD()
        code = _rstrtmgr.RmGetList(
            self.handle, ctypes.byref(needed), ctypes.byref(count), None, ctypes.byref(reasons)
        )
        if code not in (0, _ERROR_MORE_DATA) or not needed.value:
            return []
        infos = (_ProcessInfo * needed.value)()
        count = wintypes.UINT(needed.value)
        code = _rstrtmgr.RmGetList(
            self.handle, ctypes.byref(needed), ctypes.byref(count), infos, ctypes.byref(reasons)
        )
        if code:
            return []
        return [
            LockingProcess(
                pid=int(info.Process.dwProcessId),
                name=info.strAppName,
                service=(info.strServiceShortName or None)
                if info.ApplicationType == _SERVICE
                else None,
                critical=info.ApplicationType == _CRITICAL,
                started=_filetime(info.Process.ProcessStartTime),
                console=info.ApplicationType == _CONSOLE,
            )
            for info in infos[: count.value]
        ]

    def shutdown(self) -> bool:
        return bool(_rstrtmgr.RmShutdown(self.handle, _RM_FORCE_SHUTDOWN, None) == 0)

    def close(self) -> None:
        _rstrtmgr.RmEndSession(self.handle)


def _filetime(value: wintypes.FILETIME) -> int:
    return (int(value.dwHighDateTime) << 32) | int(value.dwLowDateTime)


def _terminate(process: LockingProcess) -> bool:
    """Último recurso para un programa que no atiende el aviso de cierre (consola, colgado).
    Solo si el PID sigue siendo el mismo proceso: se compara la hora de inicio."""
    handle = _kernel32.OpenProcess(
        _PROCESS_TERMINATE | _SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, process.pid
    )
    if not handle:
        return False
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not _kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return False
        if process.started and _filetime(times[0]) != process.started:
            return False
        if not _kernel32.TerminateProcess(handle, 1):
            return False
        _kernel32.WaitForSingleObject(handle, 5000)
        return True
    finally:
        _kernel32.CloseHandle(handle)


def files_to_check(paths: Iterable[str], limit: int = MAX_FILES) -> list[str]:
    """Los archivos de esas rutas (carpetas incluidas), binarios primero, hasta `limit`."""
    binaries: list[str] = []
    others: list[str] = []
    for root in paths:
        if Path(root).is_file():
            binaries.append(root)
            continue
        for folder, _dirs, names in os.walk(root, onerror=lambda _e: None):
            for name in names:
                target = binaries if Path(name).suffix.lower() in _BINARY else others
                target.append(str(Path(folder, name)))
            # Una carpeta enorme no se recorre entera: con esto basta para saber quién la usa.
            if len(binaries) >= limit or len(binaries) + len(others) >= limit * 4:
                break
    return (binaries + others)[:limit]


def processes_using(paths: Iterable[str]) -> list[LockingProcess]:
    files = files_to_check(paths)
    if not files:
        return []
    session = _Session(files)
    try:
        return session.processes()
    finally:
        session.close()


def close_processes_using(paths: Iterable[str]) -> list[LockingProcess]:
    """Cierra lo que usa esos archivos (primero con aviso al programa, después a la fuerza).
    Devuelve lo que sigue en uso: los procesos críticos solo se liberan reiniciando."""
    targets = list(paths)
    files = files_to_check(targets)
    if not files:
        return []
    session = _Session(files)
    try:
        found = session.processes()
        if not found:
            return []
        # El aviso de cierre solo sirve a programas con ventana y servicios; a uno de consola lo
        # haría esperar el tiempo de gracia completo sin resultado.
        if any(not p.console for p in found):
            session.shutdown()
        # Lo que no atendió el aviso (consola, colgado) se termina; servicios y procesos críticos
        # no: los servicios se detienen por su vía y lo crítico solo se libera reiniciando.
        for process in session.processes():
            if not process.service and not process.critical:
                _terminate(process)
    finally:
        session.close()
    # Una sesión nueva: la anterior conserva la lista de antes del cierre.
    return processes_using(targets)


_kernel32.K32EnumProcesses.argtypes = (
    ctypes.POINTER(wintypes.DWORD),
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
)
_kernel32.QueryFullProcessImageNameW.argtypes = (
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
)


def running_from(paths: Iterable[str]) -> list[LockingProcess]:
    """Procesos cuyo ejecutable está dentro de esas carpetas. Es la revisión rápida (milisegundos)
    para antes de confirmar; Restart Manager, más completo pero de segundos, queda para actuar."""
    roots = [str(Path(p)).lower().rstrip("\\") + "\\" for p in paths]
    if not roots:
        return []
    pids = (wintypes.DWORD * 4096)()
    used = wintypes.DWORD()
    if not _kernel32.K32EnumProcesses(pids, ctypes.sizeof(pids), ctypes.byref(used)):
        return []
    found = []
    for pid in pids[: used.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            continue
        try:
            buffer = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buffer))
            if not _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                continue
            image = buffer.value
        finally:
            _kernel32.CloseHandle(handle)
        if any(image.lower().startswith(root) for root in roots):
            found.append(
                LockingProcess(pid=int(pid), name=Path(image).name, service=None, critical=False)
            )
    return found

"""Abrir la interfaz con los datos de ejecución del navegador dentro de la carpeta de datos.

Se prefiere Microsoft Edge (viene con Windows) en una ventana de aplicación con su perfil en la
carpeta de datos de Honey Check: la sesión, que contiene datos del inventario, no se mezcla con
el perfil personal del usuario. Si Edge no está, se usa el navegador predeterminado.

La ventana usa archivos de la carpeta de datos, así que Honey Check la cierra al salir: de lo
contrario la USB no se podría expulsar.
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
import os
import subprocess
import time
import webbrowser
import winreg
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger(__name__)

_APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
_DETACHED = 0x00000008  # DETACHED_PROCESS: no hereda la consola ni el Job de Honey Check
_NO_WINDOW = 0x08000000
_QUERY_LIMITED = 0x1000
_PID_FILE = "navegador.pid"
_CLOSE_WAIT_S = 4.0

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = (
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
)
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


def find_edge() -> Path | None:
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, _APP_PATHS, 0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, "")
        except OSError:
            continue
        path = Path(str(value).strip('"'))
        if path.is_file():
            return path
    for base in (os.environ.get("PROGRAMFILES(X86)"), os.environ.get("PROGRAMFILES")):
        if base:
            path = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if path.is_file():
                return path
    return None


def edge_arguments(url: str, profile: Path) -> list[str]:
    return [
        f"--user-data-dir={profile}",
        f"--app={url}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
    ]


def _image_name(pid: int) -> str | None:
    handle = _kernel32.OpenProcess(_QUERY_LIMITED, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return Path(buffer.value).name.lower()
    finally:
        _kernel32.CloseHandle(handle)


def _taskkill(pid: int, *, force: bool) -> None:
    root = os.environ.get("SYSTEMROOT") or r"C:\Windows"
    args = [str(Path(root) / "System32" / "taskkill.exe"), "/PID", str(pid), "/T"]
    subprocess.run(  # noqa: S603 - herramienta de Windows con argumentos fijos
        [*args, "/F"] if force else args,
        capture_output=True,
        check=False,
        creationflags=_NO_WINDOW,
    )


class AppWindow:
    """La ventana de Edge que abrió Honey Check, anotada en la carpeta de datos."""

    def __init__(self, data_root: Path) -> None:
        self._profile = data_root / "navegador"
        self._pid_file = data_root / _PID_FILE

    def open(self, url: str) -> bool:
        """True si algún navegador aceptó abrir la URL."""
        edge = find_edge()
        if edge is not None:
            try:
                self._profile.mkdir(parents=True, exist_ok=True)
                process = subprocess.Popen(  # noqa: S603 - Edge de Windows con argumentos fijos
                    [str(edge), *edge_arguments(url, self._profile)],
                    creationflags=_DETACHED,
                    close_fds=True,
                )
            except OSError as error:
                log.warning("Edge no se pudo abrir (%s)", type(error).__name__)
            else:
                with contextlib.suppress(OSError):
                    self._pid_file.write_text(str(process.pid), encoding="ascii")
                return True
        return webbrowser.open(url)

    def close(self) -> None:
        """Cierra la ventana anotada si sigue siendo Edge (un PID puede haberse reutilizado)."""
        try:
            pid = int(self._pid_file.read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            return
        if _image_name(pid) == "msedge.exe":
            _taskkill(pid, force=False)
            deadline = time.monotonic() + _CLOSE_WAIT_S
            while time.monotonic() < deadline and _image_name(pid) == "msedge.exe":
                time.sleep(0.2)
            if _image_name(pid) == "msedge.exe":
                _taskkill(pid, force=True)
        with contextlib.suppress(OSError):
            self._pid_file.unlink()

"""Operaciones de Windows con varias vías: si la principal falla, se prueba la siguiente.

Cada operación verifica el estado final en lugar de confiar en el código de salida.
"""

from __future__ import annotations

import ctypes
import re
import time
from ctypes import wintypes

from honey_check.application.ports import CancelToken, CimQuery
from honey_check.application.support.context import Attempt, first_that_works
from honey_check.application.support.ports import CommandOutput, ToolContext
from honey_check.infrastructure.windows.com import ComError
from honey_check.infrastructure.windows.wmi import WmiCim, call_method

from .runner import tool_path

SC = tool_path("sc.exe")
POWERSHELL = tool_path("WindowsPowerShell", "v1.0", "powershell.exe")
_SERVICE_NAME = re.compile(r"^[A-Za-z0-9_.$ -]{1,128}$")
_STATE_CODE = re.compile(r":\s*(\d)\s+[A-Z_]+")
_STATES = {
    1: "Stopped",
    2: "Start Pending",
    3: "Stop Pending",
    4: "Running",
    5: "Continue Pending",
    6: "Pause Pending",
    7: "Paused",
}


def powershell(
    ctx: ToolContext, script: str, *, timeout_s: float = 120.0, stdin: str | None = None
) -> CommandOutput:
    """PowerShell como última vía: script fijo, datos por stdin, sin perfil ni política alterada."""
    return ctx.command(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command", script],
        timeout_s=timeout_s,
        stdin=stdin,
    )


def wmi_rows(query: CimQuery, timeout_s: float = 30.0) -> list[dict[str, object]]:
    result = WmiCim().query([query], CancelToken(), timeout_s)[0]
    if result.error:
        raise OSError(result.error.message)
    return [dict(row) for row in result.rows]


def service_state(ctx: ToolContext, name: str) -> str | None:
    """Estado según WMI; si no responde, según `sc query` (código numérico, igual en cualquier
    idioma).
    """
    _check_name(name)
    try:
        rows = wmi_rows(
            CimQuery("root/cimv2", "Win32_Service", ("Name", "State"), where=f"Name='{name}'")
        )
        if rows:
            return str(rows[0].get("State"))
    except OSError:
        pass
    output = ctx.command([SC, "query", name], timeout_s=20, quiet=True)
    match = _STATE_CODE.search(output.stdout)
    return _STATES.get(int(match.group(1))) if match else None


def _check_name(name: str) -> None:
    if not _SERVICE_NAME.match(name):
        raise ValueError("nombre de servicio no válido")


def _wait_for(ctx: ToolContext, name: str, wanted: str, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        ctx.cancel.raise_if_cancelled()
        if service_state(ctx, name) == wanted:
            return True
        time.sleep(1)
    return False


def _wmi_service(name: str, method_name: str, arguments: dict[str, object] | None = None) -> bool:
    try:
        result = call_method("root/cimv2", f'Win32_Service.Name="{name}"', method_name, arguments)
    except (ComError, ValueError):
        return False
    # 0 hecho; 10 ya estaba iniciado; 5 no acepta control en su estado actual.
    return result.get("ReturnValue") in (0, 10)


def stop_service(ctx: ToolContext, name: str, timeout_s: float = 60.0) -> bool:
    _check_name(name)
    if service_state(ctx, name) == "Stopped":
        ctx.info(f"El servicio {name} ya estaba detenido")
        return True
    done = first_that_works(
        ctx,
        [
            Attempt(
                f"sc stop {name}",
                lambda: (
                    ctx.command([SC, "stop", name], timeout_s=30).exit_code in (0, 1062)
                    and _wait_for(ctx, name, "Stopped", timeout_s)
                ),
            ),
            Attempt(
                f"WMI Win32_Service.StopService ({name})",
                lambda: (
                    _wmi_service(name, "StopService") and _wait_for(ctx, name, "Stopped", timeout_s)
                ),
            ),
            Attempt(
                f"Stop-Service -Force {name}",
                lambda: (
                    powershell(ctx, f"Stop-Service -Name '{name}' -Force -ErrorAction Stop").ok
                    and _wait_for(ctx, name, "Stopped", 15)
                ),
            ),
        ],
    )
    return done is not None


def start_service(ctx: ToolContext, name: str, timeout_s: float = 60.0) -> bool:
    _check_name(name)
    if service_state(ctx, name) == "Running":
        ctx.info(f"El servicio {name} ya estaba en ejecución")
        return True
    done = first_that_works(
        ctx,
        [
            Attempt(
                f"sc start {name}",
                lambda: (
                    ctx.command([SC, "start", name], timeout_s=30).exit_code in (0, 1056)
                    and _wait_for(ctx, name, "Running", timeout_s)
                ),
            ),
            Attempt(
                f"WMI Win32_Service.StartService ({name})",
                lambda: (
                    _wmi_service(name, "StartService")
                    and _wait_for(ctx, name, "Running", timeout_s)
                ),
            ),
            Attempt(
                f"Start-Service {name}",
                lambda: (
                    powershell(ctx, f"Start-Service -Name '{name}' -ErrorAction Stop").ok
                    and _wait_for(ctx, name, "Running", 15)
                ),
            ),
        ],
    )
    return done is not None


_START_MODES = {
    "auto": ("auto", "Automatic"),
    "demand": ("demand", "Manual"),
    "disabled": ("disabled", "Disabled"),
}


def set_start_mode(ctx: ToolContext, name: str, mode: str) -> bool:
    _check_name(name)
    sc_mode, wmi_mode = _START_MODES[mode]
    done = first_that_works(
        ctx,
        [
            Attempt(
                f"sc config {name} start= {sc_mode}",
                lambda: ctx.command([SC, "config", name, "start=", sc_mode], timeout_s=30).ok,
            ),
            Attempt(
                f"WMI Win32_Service.ChangeStartMode ({name})",
                lambda: _wmi_service(name, "ChangeStartMode", {"StartMode": wmi_mode}),
            ),
            Attempt(
                f"Set-Service -StartupType {wmi_mode}",
                lambda: (
                    powershell(
                        ctx, f"Set-Service -Name '{name}' -StartupType {wmi_mode} -ErrorAction Stop"
                    ).ok
                ),
            ),
        ],
    )
    return done is not None


_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_shell32.CommandLineToArgvW.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int))
_shell32.CommandLineToArgvW.restype = ctypes.POINTER(wintypes.LPWSTR)
_kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
_kernel32.ExpandEnvironmentStringsW.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
_kernel32.ExpandEnvironmentStringsW.restype = wintypes.DWORD


def split_command_line(command: str) -> list[str]:
    """Divide un comando como lo haría Windows al lanzarlo (sin pasar por un shell)."""
    if not command.strip():
        return []  # CommandLineToArgvW con texto vacío devuelve el ejecutable actual
    expanded = ctypes.create_unicode_buffer(32768)
    _kernel32.ExpandEnvironmentStringsW(command, expanded, 32768)
    count = ctypes.c_int()
    argv = _shell32.CommandLineToArgvW(expanded.value.strip(), ctypes.byref(count))
    if not argv:
        return []
    try:
        parts = [argv[i] for i in range(count.value)]
    finally:
        _kernel32.LocalFree(argv)
    return _resolve_program(parts)


def _resolve_program(parts: list[str]) -> list[str]:
    """Rutas con espacios sin comillas (frecuentes en el Registro): se une hasta dar con el .exe."""
    from pathlib import Path

    if not parts:
        return parts
    if (
        Path(parts[0]).name.lower() in ("msiexec", "msiexec.exe")
        and not Path(parts[0]).is_absolute()
    ):
        return [tool_path("msiexec.exe"), *parts[1:]]
    if Path(parts[0]).is_file():
        return parts
    for end in range(2, len(parts) + 1):
        candidate = " ".join(parts[:end])
        if Path(candidate).is_file():
            return [candidate, *parts[end:]]
    return parts

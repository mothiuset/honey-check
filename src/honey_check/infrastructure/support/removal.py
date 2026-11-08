"""Eliminar una carpeta o archivo insistiendo por vías distintas hasta lograrlo.

Orden: Papelera; si un programa lo usa, cerrarlo y reintentar; si los permisos están rotos,
recuperarlos (con respaldo de las ACL) y reintentar; en modo forzado, borrar sin Papelera; y si
algo de Windows lo sigue reteniendo, dejarlo programado para el próximo reinicio. Cada vía queda
en el registro y el resultado dice cuál funcionó.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import stat
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path

from honey_check.application.support.ports import ToolContext
from honey_check.domain.support import Check, CheckStatus
from honey_check.infrastructure.support.runner import tool_path
from honey_check.infrastructure.windows.errors import Failure, shell_file_operation, win32
from honey_check.infrastructure.windows.locks import (
    LockingProcess,
    close_processes_using,
    processes_using,
    running_from,
)
from honey_check.infrastructure.windows.shell import send_to_recycle_bin

_DELETE = 0x00010000
_FILE_SHARE_ALL = 0x7
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_INVALID_HANDLE = wintypes.HANDLE(-1).value
_MOVEFILE_DELAY_UNTIL_REBOOT = 0x4
_ADMINISTRATORS = "*S-1-5-32-544"  # por SID: «Administradores» cambia con el idioma

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateFileW.argtypes = (
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
)
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
_kernel32.MoveFileExW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD)
_kernel32.MoveFileExW.restype = wintypes.BOOL


def _admin_roots() -> list[Path]:
    names = ("PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "SYSTEMROOT")
    return [Path(value) for name in names if (value := os.environ.get(name))]


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def needs_admin(path: Path) -> bool:
    """True si eliminarlo exige administrador: Program Files y Windows siempre; lo demás se
    comprueba pidiendo a Windows el permiso de borrado sin borrar nada."""
    if any(_within(path, root) for root in _admin_roots()):
        return True
    handle = _kernel32.CreateFileW(
        str(path),
        _DELETE,
        _FILE_SHARE_ALL,
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    if handle in (None, _INVALID_HANDLE):
        return ctypes.get_last_error() == 5
    _kernel32.CloseHandle(handle)
    return False


def _gone(path: Path) -> bool:
    return not os.path.lexists(path)


def _names(processes: list[LockingProcess]) -> str:
    return ", ".join(sorted({p.label for p in processes}))


@dataclass
class Inspection:
    """Revisión previa de una ruta, antes de pedir confirmación."""

    path: Path
    exists: bool
    needs_admin: bool = False
    in_use_by: list[LockingProcess] = field(default_factory=list)

    def check(self, *, elevated: bool) -> Check:
        label = str(self.path)
        if not self.exists:
            return Check(label=label, status=CheckStatus.SKIPPED, detail="Ya no existe")
        notes = []
        if self.in_use_by:
            notes.append(f"En uso por {_names(self.in_use_by)}: se cerrará para eliminarlo")
        if self.needs_admin and not elevated:
            notes.append("Necesita permisos de administrador: Windows los pedirá")
        status = CheckStatus.WARN if notes else CheckStatus.OK
        return Check(label=label, status=status, detail="; ".join(notes) or "Lista para eliminar")


def inspect(path: Path) -> Inspection:
    if _gone(path):
        return Inspection(path, exists=False)
    in_use = running_from([str(path)]) if path.is_dir() else []
    return Inspection(path, exists=True, needs_admin=needs_admin(path), in_use_by=in_use)


@dataclass
class Removal:
    path: Path
    ok: bool
    outcome: str
    technical: str | None = None
    pending_reboot: bool = False

    def check(self) -> Check:
        if self.pending_reboot:
            status = CheckStatus.WARN
        else:
            status = CheckStatus.OK if self.ok else CheckStatus.FAIL
        return Check(
            label=str(self.path), status=status, detail=self.outcome, technical=self.technical
        )


def _take_ownership(path: Path, ctx: ToolContext) -> bool:
    """Administradores como dueños y con control total; antes, respaldo de las ACL originales."""
    icacls = tool_path("icacls.exe")
    backup = ctx.backup_path(f"permisos_{path.name}.acl")
    target = str(path)
    ctx.command([icacls, target, "/save", str(backup), "/T", "/C", "/Q"], timeout_s=300, quiet=True)
    owner = ctx.command(
        [icacls, target, "/setowner", _ADMINISTRATORS, "/T", "/C", "/L", "/Q"],
        timeout_s=300,
        quiet=True,
    )
    grant = ctx.command(
        [icacls, target, "/grant", f"{_ADMINISTRATORS}:(OI)(CI)F", "/T", "/C", "/L", "/Q"],
        timeout_s=300,
        quiet=True,
    )
    if path.is_dir():
        ctx.command(
            [tool_path("attrib.exe"), "-r", "-s", "-h", str(path / "*"), "/S", "/D"],
            timeout_s=300,
            quiet=True,
        )
    return owner.ok or grant.ok


def _delete_permanently(path: Path) -> None:
    def clear_readonly(function: object, target: str, _error: object) -> None:
        os.chmod(target, stat.S_IWRITE)  # noqa: PTH101
        function(target)  # type: ignore[operator]

    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, onexc=clear_readonly)
    else:
        os.chmod(path, stat.S_IWRITE)  # noqa: PTH101
        path.unlink()


def _schedule_on_reboot(path: Path) -> bool:
    """Marca cada archivo y después cada carpeta (de dentro hacia fuera) para el reinicio."""
    targets: list[str] = []
    if path.is_dir() and not path.is_symlink():
        for folder, dirs, files in os.walk(path, topdown=False):
            targets.extend(str(Path(folder, name)) for name in (*files, *dirs))
    targets.append(str(path))
    return all(
        _kernel32.MoveFileExW(target, None, _MOVEFILE_DELAY_UNTIL_REBOOT) for target in targets
    )


def remove(
    path: Path, ctx: ToolContext, *, close_apps: bool = True, force: bool = False
) -> Removal:
    if _gone(path):
        return Removal(path, True, "Ya no existía")
    ctx.info(f"Eliminando {path}")
    done: list[str] = []

    def result(how: str) -> Removal:
        steps = f" ({'; '.join(done)})" if done else ""
        return Removal(path, True, f"{how}{steps}")

    code = send_to_recycle_bin(str(path))
    if _gone(path):
        return result("En la Papelera")
    last = shell_file_operation(code) if code else None
    if last:
        ctx.warn(f"Papelera: {last.message}")

    try:
        in_use = processes_using([str(path)])
    except OSError:
        in_use = []
    if in_use:
        names = _names(in_use)
        if not close_apps:
            return Removal(
                path,
                False,
                f"En uso por {names}. Ciérrelo y vuelva a intentarlo.",
                last.technical if last else None,
            )
        ctx.info(f"Cerrando lo que la usa: {names}")
        still = close_processes_using([str(path)])
        done.append(f"se cerró {names}")
        if still:
            ctx.warn(f"Sigue en uso por {_names(still)}")
        code = send_to_recycle_bin(str(path))
        if _gone(path):
            return result("En la Papelera")
        last = shell_file_operation(code) if code else last

    if not ctx.env.is_elevated:
        return Removal(
            path,
            False,
            "Windows negó el acceso: hace falta administrador.",
            last.technical if last else None,
        )

    ctx.info("Recuperando los permisos de la carpeta (respaldo de las ACL originales)")
    if _take_ownership(path, ctx):
        done.append("se recuperaron los permisos")
        code = send_to_recycle_bin(str(path))
        if _gone(path):
            return result("En la Papelera")
        last = shell_file_operation(code) if code else last

    if force:
        ctx.info("Modo forzado: eliminando sin pasar por la Papelera")
        try:
            _delete_permanently(path)
        except OSError as error:
            last = win32(error.winerror) if getattr(error, "winerror", None) else last
            ctx.warn(f"Quedan partes: {last.message if last else error}")
        if _gone(path):
            return result("Eliminada sin Papelera (modo forzado)")

    if _schedule_on_reboot(path):
        ctx.warn("Algo de Windows la sigue usando: queda programada para el próximo reinicio")
        removal = result("Se terminará de eliminar al reiniciar el equipo")
        removal.pending_reboot = True
        return removal

    if last is not None and last.failure is Failure.TOO_LONG and not force:
        return Removal(
            path, False, f"{last.message} Use el modo forzado para eliminarla.", last.technical
        )
    return Removal(
        path,
        False,
        last.message if last else "Windows no permitió eliminarla.",
        last.technical if last else None,
    )

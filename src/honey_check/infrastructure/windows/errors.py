"""Errores de Windows en palabras del técnico: qué pasó, qué hacer y el código solo como detalle.

Tres familias de códigos llegan a las herramientas: los de Win32 (GetLastError), los propios de
SHFileOperation (anteriores a Win32 y con otro significado para el mismo número) y los códigos
de salida de instaladores. Cada uno se traduce a un `Failure` que decide la siguiente vía.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
from enum import StrEnum


class Failure(StrEnum):
    NEEDS_ADMIN = "needs_admin"
    IN_USE = "in_use"
    NOT_FOUND = "not_found"
    REBOOT = "reboot"  # hecho, pero termina al reiniciar
    BUSY = "busy"  # otra instalación u operación en curso
    CANCELLED = "cancelled"
    TOO_LONG = "too_long"
    OTHER = "other"


@dataclass(frozen=True)
class Explanation:
    failure: Failure
    message: str
    technical: str


_WIN32: dict[int, tuple[Failure, str]] = {
    2: (Failure.NOT_FOUND, "El archivo ya no existe."),
    3: (Failure.NOT_FOUND, "La ruta ya no existe."),
    5: (Failure.NEEDS_ADMIN, "Windows negó el acceso: hacen falta permisos de administrador."),
    19: (Failure.NEEDS_ADMIN, "La unidad está protegida contra escritura."),
    32: (Failure.IN_USE, "Un programa lo tiene abierto."),
    33: (Failure.IN_USE, "Un programa tiene bloqueada una parte del archivo."),
    145: (Failure.IN_USE, "La carpeta no quedó vacía: algo dentro sigue en uso."),
    206: (Failure.TOO_LONG, "La ruta es demasiado larga para el Explorador."),
    1223: (Failure.CANCELLED, "Se canceló el aviso de Windows; no cambió nada."),
    1060: (Failure.NOT_FOUND, "El servicio no existe."),
    1072: (Failure.REBOOT, "El servicio quedó marcado para eliminarse al reiniciar."),
    1062: (Failure.OTHER, "El servicio no estaba en ejecución."),
}

# SHFileOperation devuelve DE_* (winerror.h no los define): el mismo número no es un Win32.
_SHELL: dict[int, tuple[Failure, str]] = {
    0x71: (Failure.OTHER, "Origen y destino son el mismo archivo."),
    0x74: (Failure.OTHER, "No se puede eliminar la raíz de una unidad."),
    0x75: (Failure.CANCELLED, "La operación se canceló."),
    0x78: (Failure.NEEDS_ADMIN, "Windows negó el acceso: hacen falta permisos de administrador."),
    0x79: (Failure.TOO_LONG, "La ruta es demasiado profunda para el Explorador."),
    0x7C: (Failure.NOT_FOUND, "La ruta no existe o no es válida."),
    0x81: (Failure.TOO_LONG, "Un nombre es demasiado largo."),
    0x86: (Failure.NEEDS_ADMIN, "El medio está protegido contra escritura."),
    0x402: (Failure.NOT_FOUND, "La ruta no existe o no es válida."),
    0x10000: (Failure.OTHER, "Error en el destino de la operación."),
}

_INSTALLER: dict[int, tuple[Failure, str]] = {
    1602: (Failure.CANCELLED, "El desinstalador se canceló."),
    1603: (Failure.OTHER, "El desinstalador falló; su registro dice por qué."),
    1605: (Failure.NOT_FOUND, "Windows ya no lo tiene registrado como instalado."),
    1618: (Failure.BUSY, "Hay otra instalación en curso. Espere a que termine o reinicie."),
    1641: (Failure.REBOOT, "Hecho; el equipo debe reiniciarse para terminar."),
    3010: (Failure.REBOOT, "Hecho; el equipo debe reiniciarse para terminar."),
}


def system_text(code: int) -> str:
    """Texto de Windows para un código Win32, en el idioma del sistema."""
    try:
        return ctypes.FormatError(code).strip()
    except (OSError, ValueError, AttributeError):
        return ""


def _technical(prefix: str, code: int, extra: str = "") -> str:
    parts = [f"{prefix} {code} (0x{code:X})", extra]
    return ": ".join(p for p in parts if p)


def win32(code: int) -> Explanation:
    failure, message = _WIN32.get(code, (Failure.OTHER, ""))
    text = system_text(code)
    message = message or text or "Windows no pudo completarlo."
    return Explanation(failure, message, _technical("Win32", code, text))


def shell_file_operation(code: int) -> Explanation:
    """Código de SHFileOperation: primero los DE_*, después los Win32 que también devuelve."""
    if code in _SHELL:
        failure, message = _SHELL[code]
        return Explanation(failure, message, _technical("SHFileOperation", code))
    explanation = win32(code)
    technical = _technical("SHFileOperation", code, system_text(code))
    return Explanation(explanation.failure, explanation.message, technical)


def installer_exit(code: int) -> Explanation:
    if code in _INSTALLER:
        failure, message = _INSTALLER[code]
        return Explanation(failure, message, _technical("Código de salida", code))
    if code in _WIN32:
        return win32(code)
    technical = _technical("Código de salida", code)
    return Explanation(Failure.OTHER, "El desinstalador terminó con un error.", technical)

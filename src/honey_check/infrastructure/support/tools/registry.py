"""Registro: navegar, buscar, exportar, crear o cambiar valores y eliminar, siempre con respaldo .reg."""

from __future__ import annotations

import contextlib
import ctypes
import time
import winreg
from ctypes import wintypes

from honey_check.application.support.context import Attempt, first_that_works
from honey_check.application.support.ports import ToolContext
from honey_check.domain.support import FileRef, Risk, Tone, ToolResult

from ..base import (
    Params,
    SupportTool,
    check,
    choice,
    col,
    fact,
    link,
    number,
    step,
    table,
    text,
    tool,
)
from ..runner import tool_path

REG = tool_path("reg.exe")
_KEY = r"(HKLM|HKCU|HKCR|HKU|HKCC|HKEY_LOCAL_MACHINE|HKEY_CURRENT_USER|HKEY_CLASSES_ROOT|HKEY_USERS|HKEY_CURRENT_CONFIG)(\\[^\r\n\x00]{0,1000})?"
_HIVES = {
    "HKLM": winreg.HKEY_LOCAL_MACHINE,
    "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
    "HKCU": winreg.HKEY_CURRENT_USER,
    "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
    "HKCR": winreg.HKEY_CLASSES_ROOT,
    "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
    "HKU": winreg.HKEY_USERS,
    "HKEY_USERS": winreg.HKEY_USERS,
    "HKCC": winreg.HKEY_CURRENT_CONFIG,
    "HKEY_CURRENT_CONFIG": winreg.HKEY_CURRENT_CONFIG,
}
_SHORT = {
    "HKEY_LOCAL_MACHINE": "HKLM",
    "HKEY_CURRENT_USER": "HKCU",
    "HKEY_CLASSES_ROOT": "HKCR",
    "HKEY_USERS": "HKU",
    "HKEY_CURRENT_CONFIG": "HKCC",
}
_TYPES = {
    winreg.REG_SZ: "REG_SZ",
    winreg.REG_EXPAND_SZ: "REG_EXPAND_SZ",
    winreg.REG_DWORD: "REG_DWORD",
    winreg.REG_QWORD: "REG_QWORD",
    winreg.REG_MULTI_SZ: "REG_MULTI_SZ",
    winreg.REG_BINARY: "REG_BINARY",
}
_VIEW = winreg.KEY_WOW64_64KEY
# Claves cuya pérdida deja el equipo sin arrancar o sin usuarios: no se borran desde aquí.
_PROTECTED = (
    r"HKLM\SYSTEM",
    r"HKLM\SAM",
    r"HKLM\SECURITY",
    r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon",
    r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion",
    r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion",
    r"HKLM\SOFTWARE\Policies",
)

_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
_advapi32.RegDeleteTreeW.argtypes = (wintypes.HKEY, wintypes.LPCWSTR)
_advapi32.RegDeleteTreeW.restype = wintypes.LONG


def split(path: str) -> tuple[int, str, str]:
    """Colmena, subclave y forma corta de la ruta (HKLM\\…)."""
    root, _, sub = path.strip().strip("\\").partition("\\")
    hive = _HIVES.get(root.upper())
    if hive is None:
        raise ValueError(f"Colmena desconocida: {root}")
    short = _SHORT.get(root.upper(), root.upper())
    return hive, sub, f"{short}\\{sub}" if sub else short


def _is_protected(short: str) -> bool:
    upper = short.upper().rstrip("\\")
    return any(upper == p.upper() for p in _PROTECTED) or upper.count("\\") < 2


def is_policy(short: str) -> bool:
    """Claves de directivas (GPO): Honey Check las lee pero nunca las escribe ni las borra."""
    return "POLICIES" in short.upper().split("\\")


def refuse_policy(short: str) -> None:
    if is_policy(short):
        raise PermissionError(f"{short} es una clave de directivas: se administra por GPO, no aquí")


def _writable(key: str) -> str:
    """Al armar el plan: una clave de directivas se rechaza antes de pedir confirmación."""
    refuse_policy(split(key)[2])
    return "Las claves de directivas (GPO) nunca se modifican desde Honey Check"


def _format(value: object, kind: int) -> str:
    if kind == winreg.REG_BINARY and isinstance(value, bytes):
        return value[:64].hex(" ") + (" …" if len(value) > 64 else "")
    if isinstance(value, list):
        return " | ".join(str(v) for v in value)
    return str(value)[:500]


def _browse(params: Params, _ctx: ToolContext) -> ToolResult:
    hive, sub, short = split(params["key"])
    with winreg.OpenKey(hive, sub, 0, winreg.KEY_READ | _VIEW) as key:
        subkeys, values, _ = winreg.QueryInfoKey(key)
        children = [winreg.EnumKey(key, i) for i in range(min(subkeys, 2000))]
        entries = []
        for i in range(min(values, 2000)):
            name, data, kind = winreg.EnumValue(key, i)
            entries.append(
                {
                    "id": name or "(predeterminado)",
                    "name": name or "(predeterminado)",
                    "raw_name": name,
                    "type": _TYPES.get(kind, str(kind)),
                    "data": _format(data, kind),
                }
            )
    parent = short.rsplit("\\", 1)[0] if "\\" in short else short
    return ToolResult(
        summary=[fact("Clave", short), fact("Subclaves", subkeys), fact("Valores", values)],
        tables=[
            table(
                "clave",
                "Esta clave",
                [col("path", "Ruta")],
                [{"path": short, "parent": parent}],
                "path",
                actions=[
                    link("registry.browse", "Subir un nivel", key="{parent}"),
                    link("registry.export", "Exportar .reg", key="{path}"),
                    link("registry.delete", "Eliminar la clave", Tone.BAD, key="{path}", value=""),
                ],
            ),
            table(
                "subclaves",
                "Subclaves",
                [col("name", "Subclave")],
                [{"name": c, "path": f"{short}\\{c}"} for c in sorted(children, key=str.lower)],
                "path",
                actions=[link("registry.browse", "Abrir", key="{path}")],
            ),
            table(
                "valores",
                "Valores",
                [col("name", "Nombre"), col("type", "Tipo"), col("data", "Datos")],
                [dict(e, key=short) for e in entries],
                "id",
                actions=[
                    link(
                        "registry.delete",
                        "Eliminar valor",
                        Tone.BAD,
                        key="{key}",
                        value="{raw_name}",
                    )
                ],
            ),
        ],
    )


browse = SupportTool(
    tool(
        "registry.browse",
        "Registro",
        "Navegar el Registro",
        "Muestra subclaves y valores de una clave; desde ahí se exporta, se busca o se elimina con respaldo.",
        Risk.READ,
        params=[text("key", "Clave", required=True, pattern=_KEY, default="HKCU\\Software")],
    ),
    lambda p, _e: [step(f"Leer {p['key']}", f'reg query "{p["key"]}"')],
    _browse,
)


def _search(params: Params, ctx: ToolContext) -> ToolResult:
    hive, sub, short = split(params["key"])
    needle = params["text"].lower()
    deadline = time.monotonic() + int(params["seconds"])
    rows: list[dict[str, str]] = []
    stack = [(sub, short, 0)]
    visited = 0
    while stack and len(rows) < 500 and time.monotonic() < deadline:
        ctx.cancel.raise_if_cancelled()
        current, label, depth = stack.pop()
        visited += 1
        if visited % 500 == 0:
            ctx.progress(visited, 0, label)
        try:
            with winreg.OpenKey(hive, current, 0, winreg.KEY_READ | _VIEW) as key:
                subkeys, values, _ = winreg.QueryInfoKey(key)
                for i in range(values):
                    name, data, kind = winreg.EnumValue(key, i)
                    text_value = _format(data, kind)
                    if needle in (name or "").lower() or needle in text_value.lower():
                        rows.append(
                            {
                                "id": f"{label}|{name}",
                                "key": label,
                                "name": name or "(predeterminado)",
                                "raw_name": name,
                                "data": text_value,
                            }
                        )
                for i in range(subkeys):
                    child = winreg.EnumKey(key, i)
                    if needle in child.lower():
                        rows.append(
                            {
                                "id": f"{label}\\{child}",
                                "key": f"{label}\\{child}",
                                "name": "(clave)",
                                "raw_name": "",
                                "data": "",
                            }
                        )
                    if depth < 12:
                        stack.append(
                            (
                                f"{current}\\{child}" if current else child,
                                f"{label}\\{child}",
                                depth + 1,
                            )
                        )
        except OSError:
            continue
    complete = not stack
    return ToolResult(
        summary=[
            fact("Coincidencias", len(rows)),
            fact("Claves revisadas", visited),
            fact(
                "Búsqueda completa",
                "Sí" if complete else "No: se alcanzó el límite de tiempo o de resultados",
                Tone.NEUTRAL if complete else Tone.WARN,
            ),
        ],
        tables=[
            table(
                "resultados",
                "Resultados",
                [col("key", "Clave"), col("name", "Valor"), col("data", "Datos", priority=2)],
                rows,
                "id",
                actions=[
                    link("registry.browse", "Abrir clave", key="{key}"),
                    link("registry.delete", "Eliminar", Tone.BAD, key="{key}", value="{raw_name}"),
                ],
            )
        ],
    )


search = SupportTool(
    tool(
        "registry.search",
        "Registro",
        "Buscar en el Registro",
        "Busca un texto en nombres de claves, valores y datos bajo una clave, con límite de tiempo.",
        Risk.READ,
        params=[
            text("key", "Buscar dentro de", required=True, pattern=_KEY, default="HKCU\\Software"),
            text("text", "Texto", required=True),
            number("seconds", "Segundos máximos", default=60),
        ],
    ),
    lambda p, _e: [
        step(f"Buscar «{p['text']}» en {p['key']}", f'reg query "{p["key"]}" /s /f "{p["text"]}"')
    ],
    _search,
)


def export_key(ctx: ToolContext, short: str, *, backup: bool) -> FileRef | None:
    name = short.replace("\\", "_")[-80:] + ".reg"
    target = ctx.backup_path(name) if backup else ctx.output_path(name)
    output = ctx.command([REG, "export", short, str(target), "/y", "/reg:64"], timeout_s=120)
    if output.ok and target.is_file():
        return FileRef(label="Respaldo .reg" if backup else "Exportación .reg", path=str(target))
    return None


def _export(params: Params, ctx: ToolContext) -> ToolResult:
    _, _, short = split(params["key"])
    file = export_key(ctx, short, backup=False)
    return ToolResult(
        files=[file] if file else [],
        checks=[check("Exportado", file is not None)],
        verified=file is not None,
    )


export = SupportTool(
    tool(
        "registry.export",
        "Registro",
        "Exportar clave",
        "Guarda la clave y sus subclaves en un archivo .reg dentro de la carpeta de datos.",
        Risk.READ,
        params=[text("key", "Clave", required=True, pattern=_KEY)],
        hidden=True,
        instant=True,
    ),
    lambda p, _e: [step("Exportar", f'reg export "{p["key"]}" archivo.reg /y')],
    _export,
)


def _exists(hive: int, sub: str, value: str | None) -> bool:
    try:
        with winreg.OpenKey(hive, sub, 0, winreg.KEY_READ | _VIEW) as key:
            if value is None:
                return True
            winreg.QueryValueEx(key, value)
            return True
    except OSError:
        return False


def _delete(params: Params, ctx: ToolContext) -> ToolResult:
    hive, sub, short = split(params["key"])
    value = params.get("value")
    is_value = value is not None and value != ""
    refuse_policy(short)
    if not is_value and _is_protected(short):
        raise PermissionError(f"{short} es una clave del sistema protegida")
    backup = export_key(ctx, short, backup=True)
    if backup is None:
        raise RuntimeError("No se pudo crear el respaldo .reg: no se elimina nada")

    def native() -> bool:
        if is_value:
            with winreg.OpenKey(hive, sub, 0, winreg.KEY_SET_VALUE | _VIEW) as key:
                winreg.DeleteValue(key, str(value))
        else:
            parent, _, leaf = sub.rpartition("\\")
            with winreg.OpenKey(hive, parent, 0, winreg.KEY_ALL_ACCESS | _VIEW) as key:
                if _advapi32.RegDeleteTreeW(key.handle, leaf) != 0:
                    return False
                with contextlib.suppress(OSError):  # según la versión, RegDeleteTree ya la borró
                    winreg.DeleteKeyEx(key, leaf, _VIEW)
        return not _exists(hive, sub, value if is_value else None)

    def tool_reg() -> bool:
        args = [REG, "delete", short, "/f", "/reg:64"] + (["/v", str(value)] if is_value else [])
        return ctx.command(args, timeout_s=60).ok and not _exists(
            hive, sub, value if is_value else None
        )

    first_that_works(ctx, [Attempt("API del Registro", native), Attempt("reg delete", tool_reg)])
    gone = not _exists(hive, sub, value if is_value else None)
    label = f"{short} → {value}" if is_value else short
    return ToolResult(
        checks=[check(label, gone, "Eliminado" if gone else "Sigue existiendo")],
        files=[backup],
        verified=gone,
    )


delete = SupportTool(
    tool(
        "registry.delete",
        "Registro",
        "Eliminar del Registro",
        "Elimina un valor o una clave completa después de exportar un respaldo .reg (doble clic en el .reg lo restaura).",
        Risk.DESTRUCTIVE,
        params=[
            text("key", "Clave", required=True, pattern=_KEY),
            text("value", "Valor (vacío para eliminar la clave completa)"),
        ],
        hidden=True,
    ),
    lambda p, _e: [
        step("Comprobar que no es una clave de directivas", detail=_writable(p["key"])),
        step("Respaldar la clave", f'reg export "{p["key"]}" respaldo.reg /y'),
        step(
            f"Eliminar {'el valor ' + p['value'] if p.get('value') else 'la clave y sus subclaves'}",
            f'reg delete "{p["key"]}"' + (f' /v "{p["value"]}"' if p.get("value") else "") + " /f",
        ),
        step("Comprobar que ya no existe"),
    ],
    _delete,
    backup="Archivo .reg en HoneyCheck-datos\\respaldos (doble clic para restaurar)",
)

_KINDS = [
    ("REG_SZ", "Texto (REG_SZ)"),
    ("REG_DWORD", "Número 32 bits (REG_DWORD)"),
    ("REG_QWORD", "Número 64 bits (REG_QWORD)"),
    ("REG_EXPAND_SZ", "Texto expandible"),
    ("REG_MULTI_SZ", "Varias líneas (separe con |)"),
]


def _set(params: Params, ctx: ToolContext) -> ToolResult:
    hive, sub, short = split(params["key"])
    refuse_policy(short)
    kind_name, name, raw = params["kind"], params["name"], params["data"]
    kind = {v: k for k, v in _TYPES.items()}[kind_name]
    data: int | str | list[str] = (
        int(raw, 0)
        if kind in (winreg.REG_DWORD, winreg.REG_QWORD)
        else (raw.split("|") if kind == winreg.REG_MULTI_SZ else raw)
    )
    backup = export_key(ctx, short, backup=True) if _exists(hive, sub, None) else None

    def native() -> bool:
        with winreg.CreateKeyEx(hive, sub, 0, winreg.KEY_SET_VALUE | _VIEW) as key:
            winreg.SetValueEx(key, name, 0, kind, data)
        return True

    def tool_reg() -> bool:
        text_data = "\\0".join(data) if isinstance(data, list) else str(data)
        return ctx.command(
            [REG, "add", short, "/v", name, "/t", kind_name, "/d", text_data, "/f", "/reg:64"],
            timeout_s=60,
        ).ok

    first_that_works(ctx, [Attempt("API del Registro", native), Attempt("reg add", tool_reg)])
    try:
        with winreg.OpenKey(hive, sub, 0, winreg.KEY_READ | _VIEW) as key:
            current, _ = winreg.QueryValueEx(key, name)
        ok = current == data
    except OSError:
        ok = False
    return ToolResult(
        checks=[
            check(
                f"{short} → {name}",
                ok,
                "Valor escrito y verificado" if ok else "No se pudo verificar",
            )
        ],
        files=[backup] if backup else [],
        verified=ok,
    )


set_value = SupportTool(
    tool(
        "registry.set",
        "Registro",
        "Crear o cambiar un valor",
        "Escribe un valor del Registro con respaldo .reg previo de la clave y verificación.",
        Risk.CHANGE,
        params=[
            text("key", "Clave", required=True, pattern=_KEY),
            text("name", "Nombre del valor", required=True),
            choice("kind", "Tipo", _KINDS),
            text("data", "Datos", required=True, help="Números en decimal o 0x hexadecimal"),
        ],
    ),
    lambda p, _e: [
        step("Comprobar que no es una clave de directivas", detail=_writable(p["key"])),
        step("Respaldar la clave", f'reg export "{p["key"]}" respaldo.reg /y'),
        step(
            "Escribir el valor",
            f'reg add "{p["key"]}" /v "{p["name"]}" /t {p["kind"]} /d "{p["data"]}" /f',
        ),
        step("Leer y comprobar"),
    ],
    _set,
    backup="Archivo .reg en HoneyCheck-datos\\respaldos",
)

TOOLS = [browse, search, export, delete, set_value]

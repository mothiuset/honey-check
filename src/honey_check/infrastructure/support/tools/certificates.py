"""Certificados: listar con filtros, exportar, eliminar con respaldo e instalar."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from honey_check.application.support.context import Attempt, first_that_works
from honey_check.application.support.ports import SupportEnvironment, ToolContext
from honey_check.domain.support import ColumnKind, FileRef, Risk, Tone, ToolResult
from honey_check.infrastructure.windows.crypt32 import (
    STORE_NAMES,
    CertificateRecord,
    StoreLocation,
    delete_certificate,
    list_certificates,
)

from ..base import (
    Params,
    SupportTool,
    check,
    choice,
    col,
    fact,
    link,
    number,
    secret,
    step,
    table,
    text,
    tool,
)
from ..runner import tool_path

CERTUTIL = tool_path("certutil.exe")
_THUMBPRINT = r"[0-9A-Fa-f]{40}"
_LOCATION = choice(
    "location",
    "Ubicación",
    [(StoreLocation.CURRENT_USER, "Usuario actual"), (StoreLocation.LOCAL_MACHINE, "Equipo")],
)
_STORE = choice("store", "Almacén", [(name, name) for name in STORE_NAMES])
_CN = re.compile(r"CN=([^,]+)")


def _common_name(dn: str | None) -> str | None:
    if not dn:
        return None
    match = _CN.search(dn)
    return match.group(1).strip() if match else dn


def _find(location: str, store: str, thumbprint: str) -> CertificateRecord | None:
    return next(
        (c for c in list_certificates(location, store) if c.thumbprint == thumbprint.upper()), None
    )


# --- Listar -------------------------------------------------------------------------------------


def _list(params: Params, ctx: ToolContext) -> ToolResult:
    words = [w.lower() for w in str(params.get("filter") or "").split() if w]
    soon = int(params["days"])
    now = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    locations = (
        [StoreLocation.CURRENT_USER, StoreLocation.LOCAL_MACHINE]
        if params["scope"] == "all"
        else [params["scope"]]
    )
    for location in locations:
        for store in STORE_NAMES if params["stores"] == "all" else ["My"]:
            try:
                records = list(list_certificates(location, store))
            except OSError as error:
                ctx.warn(f"{location}\\{store}: {error}")
                continue
            for cert in records:
                haystack = f"{cert.subject} {cert.issuer} {cert.friendly_name}".lower()
                if words and not all(w in haystack for w in words):
                    continue
                days = (cert.not_after - now).days
                rows.append(
                    {
                        "id": f"{location}|{store}|{cert.thumbprint}",
                        "location": location,
                        "store": store,
                        "subject": _common_name(cert.subject),
                        "issuer": _common_name(cert.issuer),
                        "expires": cert.not_after.isoformat(),
                        "days": days,
                        "state": "Vencido"
                        if days < 0
                        else ("Vence pronto" if days <= soon else "Vigente"),
                        "private_key": cert.has_private_key,
                        "provider": cert.key_provider or "",
                        "thumbprint": cert.thumbprint,
                    }
                )
    rows.sort(key=lambda r: r["days"])
    expired = sum(1 for r in rows if r["days"] < 0)
    expiring = sum(1 for r in rows if 0 <= r["days"] <= soon)
    return ToolResult(
        summary=[
            fact("Certificados", len(rows)),
            fact("Vencidos", expired, Tone.BAD if expired else Tone.NEUTRAL),
            fact(
                f"Vencen en {soon} días o menos", expiring, Tone.WARN if expiring else Tone.NEUTRAL
            ),
            fact("Con clave privada", sum(1 for r in rows if r["private_key"])),
        ],
        tables=[
            table(
                "certificados",
                "Certificados",
                [
                    col("subject", "Titular"),
                    col("issuer", "Emisor"),
                    col("expires", "Vence", ColumnKind.DATE),
                    col("state", "Estado"),
                    col("private_key", "Clave privada", ColumnKind.BOOL, 2),
                    col("provider", "Proveedor de la clave (token)", priority=3),
                    col("store", "Almacén", priority=3),
                    col("location", "Ubicación", priority=3),
                    col("thumbprint", "Huella", priority=3),
                ],
                rows,
                "id",
                actions=[
                    link(
                        "certs.export",
                        "Exportar .cer",
                        location="{location}",
                        store="{store}",
                        thumbprint="{thumbprint}",
                    ),
                    link(
                        "certs.delete",
                        "Eliminar",
                        Tone.BAD,
                        location="{location}",
                        store="{store}",
                        thumbprint="{thumbprint}",
                    ),
                ],
            )
        ],
    )


list_tool = SupportTool(
    tool(
        "certs.list",
        "Certificados",
        "Certificados instalados",
        "Lista certificados del usuario y del equipo con vencimiento, clave privada y token; filtra por titular o emisor (Andes, Certicámara, GSE…).",
        Risk.READ,
        params=[
            text(
                "filter", "Buscar en titular o emisor", help="Por ejemplo: andes, certicamara, gse"
            ),
            choice(
                "scope",
                "Dónde",
                [
                    ("all", "Usuario y equipo"),
                    (StoreLocation.CURRENT_USER, "Solo usuario actual"),
                    (StoreLocation.LOCAL_MACHINE, "Solo equipo"),
                ],
            ),
            choice("stores", "Almacenes", [("my", "Personales (los de firma)"), ("all", "Todos")]),
            number("days", "Avisar si vencen en menos de (días)", default=30),
        ],
    ),
    lambda _p, _e: [step("Leer los almacenes de certificados", "certutil -user -store My")],
    _list,
)


# --- Exportar -----------------------------------------------------------------------------------


def _export(params: Params, ctx: ToolContext) -> ToolResult:
    cert = _find(params["location"], params["store"], params["thumbprint"])
    if cert is None:
        raise ValueError("El certificado ya no está en ese almacén")
    target = ctx.output_path(f"{_common_name(cert.subject) or cert.thumbprint}.cer")
    target.write_bytes(cert.der)
    ctx.info(f"Exportado a {target}")
    return ToolResult(
        files=[FileRef(label="Certificado público", path=str(target))], verified=target.is_file()
    )


_THUMB_PARAMS = [
    _LOCATION,
    _STORE,
    text("thumbprint", "Huella", required=True, pattern=_THUMBPRINT),
]

export = SupportTool(
    tool(
        "certs.export",
        "Certificados",
        "Exportar certificado",
        "Guarda el certificado público (.cer) en la carpeta de datos.",
        Risk.READ,
        params=_THUMB_PARAMS,
        hidden=True,
    ),
    lambda p, _e: [
        step(
            "Exportar el certificado público",
            f"certutil {'-user ' if p['location'] == StoreLocation.CURRENT_USER else ''}-store {p['store']} {p['thumbprint']} archivo.cer",
        )
    ],
    _export,
)


# --- Eliminar ------------------------------------------------------------------------------------


def _delete(params: Params, ctx: ToolContext) -> ToolResult:
    location, store, thumbprint = params["location"], params["store"], params["thumbprint"].upper()
    cert = _find(location, store, thumbprint)
    if cert is None:
        return ToolResult(
            checks=[check("Certificado", None, "Ya no estaba en el almacén")], verified=True
        )
    backup = ctx.backup_path(f"{_common_name(cert.subject) or thumbprint}.cer")
    backup.write_bytes(cert.der)
    ctx.info(f"Respaldo del certificado público: {backup}")
    user = ["-user"] if location == StoreLocation.CURRENT_USER else []
    first_that_works(
        ctx,
        [
            Attempt(
                "API de certificados de Windows",
                lambda: delete_certificate(location, store, thumbprint),
            ),
            Attempt(
                "certutil -delstore",
                lambda: (
                    ctx.command([CERTUTIL, *user, "-delstore", store, thumbprint], timeout_s=60).ok
                ),
            ),
        ],
    )
    gone = _find(location, store, thumbprint) is None
    detail = "Eliminado" if gone else "Sigue en el almacén"
    if gone and cert.has_private_key:
        detail += ". La clave privada no se puede respaldar desde aquí: si estaba en un token, sigue en el token."
    return ToolResult(
        checks=[check(_common_name(cert.subject) or thumbprint, gone, detail)],
        files=[FileRef(label="Respaldo (.cer)", path=str(backup))],
        verified=gone,
    )


def _delete_warnings(params: Params, _env: SupportEnvironment) -> list[str]:
    cert = _find(params["location"], params["store"], params["thumbprint"])
    if cert and cert.has_private_key:
        return [
            "Tiene clave privada: el respaldo solo guarda la parte pública. Sin la clave, no podrá volver a firmar con él."
        ]
    return []


delete = SupportTool(
    tool(
        "certs.delete",
        "Certificados",
        "Eliminar certificado",
        "Elimina un certificado del almacén con respaldo previo del certificado público.",
        Risk.DESTRUCTIVE,
        params=_THUMB_PARAMS,
        hidden=True,
    ),
    lambda p, _e: [
        step("Respaldar el certificado público en HoneyCheck-datos\\respaldos"),
        step(
            "Eliminar del almacén",
            f"certutil {'-user ' if p['location'] == StoreLocation.CURRENT_USER else ''}-delstore {p['store']} {p['thumbprint']}",
        ),
        step("Comprobar que ya no está"),
    ],
    _delete,
    warnings=_delete_warnings,
    backup="Certificado público (.cer) en HoneyCheck-datos\\respaldos",
)


# --- Instalar ------------------------------------------------------------------------------------


def _install(params: Params, ctx: ToolContext) -> ToolResult:
    path = Path(params["file"])
    if not path.is_file():
        raise ValueError(f"No existe {path}")
    user = ["-user"] if params["location"] == StoreLocation.CURRENT_USER else []
    if path.suffix.lower() in (".pfx", ".p12"):
        password = str(params.get("password") or "")
        output = ctx.command(
            [CERTUTIL, *user, "-f", "-p", password, "-importPFX", params["store"], str(path)],
            timeout_s=120,
        )
    else:
        output = ctx.command(
            [CERTUTIL, *user, "-f", "-addstore", params["store"], str(path)], timeout_s=120
        )
    return ToolResult(
        checks=[
            check(
                path.name,
                output.ok,
                output.stdout.strip().splitlines()[-1] if output.stdout.strip() else None,
            )
        ],
        verified=output.ok,
    )


install = SupportTool(
    tool(
        "certs.install",
        "Certificados",
        "Instalar certificado",
        "Instala un .cer, .crt, .p7b o .pfx (con contraseña) en el almacén elegido.",
        Risk.CHANGE,
        params=[
            text(
                "file",
                "Archivo",
                required=True,
                pattern=r"[A-Za-z]:\\[^<>\"|?*\x00]{1,400}\.(cer|crt|p7b|pfx|p12)",
                help="Ruta completa, por ejemplo E:\\HoneyCheck-datos\\certificados\\firma.pfx",
            ),
            _LOCATION,
            choice(
                "store",
                "Almacén",
                [
                    ("My", "Personal (firma)"),
                    ("Root", "Raíz de confianza"),
                    ("CA", "Entidades intermedias"),
                    ("TrustedPeople", "Personas de confianza"),
                ],
            ),
            secret(
                "password",
                "Contraseña del .pfx",
                help="Solo para .pfx/.p12; no se guarda ni se registra",
            ),
        ],
    ),
    lambda p, _e: [
        step(
            "Importar el certificado",
            f'certutil {"-user " if p["location"] == StoreLocation.CURRENT_USER else ""}-addstore {p["store"]} "{p["file"]}"',
        )
    ],
    _install,
)

TOOLS = [list_tool, export, delete, install]

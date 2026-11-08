"""Procesos de instalación y listas de chequeo: definición versionada, plantillas y ejecución.

Un proceso es una lista ordenada de pasos. Los automáticos los ejecuta Honey Check; los manuales
los marca el técnico. Cada definición se guarda como versión nueva (nunca se sobrescribe) y cada
ejecución recuerda el estado de sus pasos para poder reanudarse.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator

from .observed import Model

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


class StepKind(StrEnum):
    INSTALL = "install"  # instalador de HoneyCheck-datos\instaladores
    VERIFY_PROGRAM = "verify_program"
    VERIFY_CERTIFICATE = "verify_certificate"
    VERIFY_SERVICE = "verify_service"
    VERIFY_FILE = "verify_file"
    TOOL = "tool"  # una herramienta de soporte con sus parámetros
    COMMAND = "command"  # programa con argumentos
    MANUAL = "manual"  # lo hace y lo marca el técnico
    REBOOT = "reboot"


class ProcedureStep(Model):
    id: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    kind: StepKind
    title: str = Field(min_length=1, max_length=200)
    params: dict[str, Any] = Field(default_factory=dict)
    optional: bool = False
    help: str | None = None


class Procedure(Model):
    slug: str
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    version: int = 0
    steps: list[ProcedureStep] = Field(min_length=1, max_length=100)
    saved_at: datetime | None = None
    template: bool = False

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not SLUG.match(value):
            raise ValueError("identificador inválido: minúsculas, números y guiones")
        return value

    @field_validator("steps")
    @classmethod
    def _unique(cls, steps: list[ProcedureStep]) -> list[ProcedureStep]:
        ids = [s.id for s in steps]
        if len(ids) != len(set(ids)):
            raise ValueError("cada paso necesita un identificador distinto")
        return steps


class StepState(StrEnum):
    PENDING = "pending"
    OK = "ok"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING = "waiting"  # manual o reinicio: espera al técnico


class StepRecord(Model):
    step: str
    state: StepState = StepState.PENDING
    detail: str | None = None
    at: datetime | None = None
    by_technician: bool = False


class ProcedureRun(Model):
    id: str
    slug: str
    version: int
    name: str
    device: str | None
    started_at: datetime
    updated_at: datetime
    steps: list[StepRecord]
    finished: bool = False

    def record(self, step_id: str) -> StepRecord:
        return next(r for r in self.steps if r.step == step_id)


def _step(id: str, kind: StepKind, title: str, **params: Any) -> ProcedureStep:
    help_text = params.pop("help", None)
    optional = params.pop("optional", False)
    return ProcedureStep(
        id=id, kind=kind, title=title, params=params, help=help_text, optional=optional
    )


TEMPLATES: list[Procedure] = [
    Procedure(
        slug="equipo-nuevo",
        name="Equipo recién formateado",
        description="Puesta a punto de un equipo después de instalar Windows.",
        template=True,
        steps=[
            _step(
                "punto",
                StepKind.TOOL,
                "Crear punto de restauración",
                tool="system.restore_point",
                tool_params={"description": "Antes de la puesta a punto"},
                optional=True,
            ),
            _step(
                "analisis",
                StepKind.MANUAL,
                "Analizar el equipo con Honey Check y revisar el panal",
                help="Panel > Analizar equipo",
            ),
            _step(
                "drivers",
                StepKind.MANUAL,
                "Instalar los drivers del fabricante (chipset, video, red, audio)",
            ),
            _step(
                "errores",
                StepKind.MANUAL,
                "Revisar que no haya dispositivos con errores",
                help="Hardware > Dispositivos con errores",
            ),
            _step(
                "actualizaciones",
                StepKind.MANUAL,
                "Instalar actualizaciones de Windows hasta que no queden pendientes",
            ),
            _step(
                "navegador",
                StepKind.INSTALL,
                "Instalar el navegador institucional",
                file="navegador.msi",
                args="",
                optional=True,
            ),
            _step(
                "pdf",
                StepKind.INSTALL,
                "Instalar el lector de PDF",
                file="lector-pdf.exe",
                args="/sAll /rs /msi EULA_ACCEPT=YES",
                optional=True,
            ),
            _step("antivirus", StepKind.MANUAL, "Instalar o comprobar el antivirus institucional"),
            _step(
                "dominio", StepKind.MANUAL, "Unir el equipo al dominio y reiniciar", optional=True
            ),
            _step(
                "directivas",
                StepKind.TOOL,
                "Aplicar directivas del dominio",
                tool="domain.gpupdate",
                tool_params={"target": "both"},
                optional=True,
            ),
            _step(
                "limpieza",
                StepKind.TOOL,
                "Limpiar temporales",
                tool="cleanup.run",
                tool_params={"categories": ["temp_user", "temp_windows"]},
            ),
            _step("reinicio", StepKind.REBOOT, "Reiniciar el equipo"),
        ],
    ),
    Procedure(
        slug="oficina",
        name="Paquete de oficina",
        description="Office, lector de PDF, compresor y comprobaciones básicas.",
        template=True,
        steps=[
            _step(
                "office",
                StepKind.INSTALL,
                "Instalar Office con la ODT",
                file="office\\setup.exe",
                args="/configure office\\configuracion.xml",
                help="Copie la ODT y su XML en HoneyCheck-datos\\instaladores\\office",
            ),
            _step(
                "office-ok",
                StepKind.VERIFY_PROGRAM,
                "Comprobar que Office quedó instalado",
                name="Microsoft 365",
            ),
            _step(
                "pdf",
                StepKind.INSTALL,
                "Instalar el lector de PDF",
                file="lector-pdf.exe",
                args="/sAll /rs",
                optional=True,
            ),
            _step(
                "zip",
                StepKind.INSTALL,
                "Instalar el compresor de archivos",
                file="7z.exe",
                args="/S",
                optional=True,
            ),
            _step(
                "zip-ok",
                StepKind.VERIFY_PROGRAM,
                "Comprobar el compresor",
                name="7-Zip",
                optional=True,
            ),
            _step(
                "activar", StepKind.MANUAL, "Iniciar sesión en Office con la cuenta institucional"
            ),
            _step(
                "impresora",
                StepKind.MANUAL,
                "Agregar la impresora del área e imprimir una página de prueba",
                help="Soporte > Impresoras",
            ),
        ],
    ),
    Procedure(
        slug="firma-digital",
        name="Firma digital (token)",
        description="Driver del token, certificados de la entidad y prueba de firma.",
        template=True,
        steps=[
            _step(
                "driver",
                StepKind.INSTALL,
                "Instalar el driver del token",
                file="token\\driver.msi",
                args="",
                help="Driver del fabricante del token (SafeNet, ePass, Feitian…)",
            ),
            _step(
                "servicio",
                StepKind.VERIFY_SERVICE,
                "Comprobar el servicio de tarjeta inteligente",
                name="SCardSvr",
                state="Running",
            ),
            _step(
                "raiz",
                StepKind.MANUAL,
                "Instalar el certificado raíz de la entidad",
                optional=True,
                help=(
                    "Soporte > Certificados > Instalar certificado, con el archivo de la"
                    " entidad (Andes, Certicámara, GSE…) en Equipo local > Raíz"
                ),
            ),
            _step(
                "conectar",
                StepKind.MANUAL,
                "Conectar el token y escribir el PIN cuando el programa lo pida",
            ),
            _step(
                "certificado",
                StepKind.VERIFY_CERTIFICATE,
                "Comprobar que el certificado del token aparece",
                text="",
                help="Escriba parte del nombre del titular o de la entidad",
            ),
            _step("firmar", StepKind.MANUAL, "Firmar un documento de prueba y validar la firma"),
        ],
    ),
]

"""Contrato de los módulos de inventario y el contexto con el que trabajan."""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel

from honey_check.domain.inventory import Issue
from honey_check.domain.observed import Observed, Reason

from .ports import CancelToken, CimError, CimErrorKind, CimQuery, CimResult, CollectorPorts

_REASON_BY_CIM_ERROR = {
    CimErrorKind.ACCESS_DENIED: Reason.ACCESS_DENIED,
    CimErrorKind.NOT_AVAILABLE: Reason.NOT_AVAILABLE,
}


def reason_for(result: CimResult) -> str:
    if result.error is None:
        return Reason.NOT_REPORTED
    return _REASON_BY_CIM_ERROR.get(result.error.kind, Reason.QUERY_FAILED)


def unknown_from[T](result: CimResult, source: str) -> Observed[T]:
    return Observed[T].unknown(reason_for(result), source)


class ModuleFailed(Exception):
    """El módulo no pudo obtener ningún dato útil."""

    def __init__(self, code: str, message: str, source: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.source = source


@dataclass
class CollectionContext:
    module: str
    ports: CollectorPorts
    cancel: CancelToken
    timeout_s: float
    warnings: list[Issue] = field(default_factory=list)
    errors: list[Issue] = field(default_factory=list)
    retries: int = 0
    attachments: dict[str, bytes] = field(default_factory=dict)

    def attach(self, data: bytes) -> str:
        """Guarda un binario del análisis y devuelve su identificador, derivado del contenido."""
        identifier = hashlib.sha256(data).hexdigest()[:16]
        self.attachments.setdefault(identifier, data)
        return identifier

    def warn(self, code: str, message: str, source: str | None = None) -> None:
        self.warnings.append(Issue(module=self.module, code=code, message=message, source=source))

    def error(self, code: str, message: str, source: str | None = None) -> None:
        self.errors.append(Issue(module=self.module, code=code, message=message, source=source))

    def query(
        self,
        queries: Sequence[CimQuery],
        timeout_s: float | None = None,
        optional: Collection[CimQuery] = (),
        admin_only: Collection[CimQuery] = (),
    ) -> list[CimResult]:
        """Consulta un lote y registra cada fallo; una clase ausente no es un error del módulo.

        Las consultas `optional` solo enriquecen el resultado: si fallan, es una advertencia.
        Las `admin_only` exigen administrador según Microsoft: sin elevación no se lanzan, porque
        Windows tarda segundos en responder «acceso denegado».
        """
        self.cancel.raise_if_cancelled()
        skipped = (
            {id(q) for q in admin_only}
            if admin_only and not self.ports.native.is_elevated()
            else set()
        )
        to_run = [q for q in queries if id(q) not in skipped]
        answered = iter(
            self.ports.cim.query(to_run, self.cancel, timeout_s or self.timeout_s) if to_run else []
        )
        denied = CimResult(error=CimError(CimErrorKind.ACCESS_DENIED, "requiere administrador"))
        results = [denied if id(q) in skipped else next(answered) for q in queries]
        for query, result in zip(queries, results, strict=True):
            self.retries += result.retries
            if result.error is None:
                continue
            if result.error.kind is CimErrorKind.NOT_AVAILABLE or query in optional:
                self.warn(result.error.kind.value, result.error.message, query.source)
            elif result.error.kind is CimErrorKind.ACCESS_DENIED:
                self.warn(result.error.kind.value, "Permisos insuficientes", query.source)
            else:
                self.error(result.error.kind.value, result.error.message, query.source)
        return results


class Collector(Protocol):
    name: str
    timeout_s: float

    def collect(self, ctx: CollectionContext) -> BaseModel: ...

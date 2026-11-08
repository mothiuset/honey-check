"""Valor observado con su procedencia: nunca se presenta un dato desconocido como real."""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic.alias_generators import to_camel


class Model(BaseModel):
    """Base de los modelos del contrato: JSON en camelCase, inmutable y sin campos ajenos."""

    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, frozen=True, extra="forbid"
    )


class Confidence(StrEnum):
    VERIFIED = "verified"  # comprobado contra el artefacto real (p. ej. cabecera PE)
    REPORTED = "reported"  # devuelto por Windows, SMBIOS o el Registro, sin verificación propia
    INFERRED = "inferred"  # calculado con una regla determinista a partir de datos reportados
    PROBABLE = "probable"  # candidato heurístico: puede ser incorrecto
    UNKNOWN = "unknown"  # no pudo determinarse


class Reason:
    """Códigos estables que explican por qué un valor es desconocido."""

    NOT_REPORTED = "not_reported_by_windows"
    PLACEHOLDER = "placeholder_value"
    ACCESS_DENIED = "access_denied"
    QUERY_FAILED = "query_failed"
    NOT_AVAILABLE = "not_available_on_this_system"
    INVALID_VALUE = "invalid_value"
    NOT_APPLICABLE = "not_applicable"
    NOT_RESOLVED = "not_resolved"
    NOT_CHECKED = "not_checked"


class Observed[T](Model):
    value: T | None = None
    confidence: Confidence = Confidence.UNKNOWN
    source: str | None = None
    reason: str | None = None
    raw: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.value is None:
            if self.confidence is not Confidence.UNKNOWN:
                raise ValueError("un valor nulo solo puede tener confianza 'unknown'")
            if not self.reason:
                raise ValueError("un valor desconocido debe declarar el motivo")
        else:
            if self.confidence is Confidence.UNKNOWN:
                raise ValueError("un valor presente no puede tener confianza 'unknown'")
            if not self.source:
                raise ValueError("un valor presente debe declarar su origen")
        return self

    @classmethod
    def reported(cls, value: T, source: str) -> Self:
        return cls(value=value, confidence=Confidence.REPORTED, source=source)

    @classmethod
    def verified(cls, value: T, source: str) -> Self:
        return cls(value=value, confidence=Confidence.VERIFIED, source=source)

    @classmethod
    def inferred(cls, value: T, source: str) -> Self:
        return cls(value=value, confidence=Confidence.INFERRED, source=source)

    @classmethod
    def probable(cls, value: T, source: str, reason: str | None = None) -> Self:
        return cls(value=value, confidence=Confidence.PROBABLE, source=source, reason=reason)

    @classmethod
    def unknown(cls, reason: str, source: str | None = None, raw: str | None = None) -> Self:
        return cls(reason=reason, source=source, raw=raw)

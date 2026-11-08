"""Validación de parámetros contra la definición de la herramienta: la petición no aporta nada
más.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from honey_check.domain.support import Param, ParamKind, ToolDefinition


class InvalidParams(ValueError):
    def __init__(self, field: str, reason: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.field = field
        self.reason = reason


def _one(param: Param, raw: Any) -> Any:
    if param.kind is ParamKind.BOOL:
        if isinstance(raw, bool):
            return raw
        raise InvalidParams(param.name, "debe ser verdadero o falso")
    if param.kind is ParamKind.NUMBER:
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise InvalidParams(param.name, "debe ser un número")
        return raw
    if param.kind is ParamKind.MULTI:
        if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
            raise InvalidParams(param.name, "debe ser una lista de textos")
        if len(raw) > 500:
            raise InvalidParams(param.name, "demasiados elementos")
        for item in raw:
            _text(param, item)
        return list(raw)
    return _text(param, raw)


def _text(param: Param, raw: Any) -> str:
    if not isinstance(raw, str):
        raise InvalidParams(param.name, "debe ser texto")
    if len(raw) > param.max_length or "\x00" in raw:
        raise InvalidParams(param.name, "valor no permitido")
    # Con fuente en vivo (impresoras, discos) las opciones no están en la definición: el patrón
    # limita el valor y la herramienta comprueba que exista al ejecutarse.
    if (
        param.kind is ParamKind.CHOICE
        and not param.source
        and raw not in {choice.value for choice in param.choices}
    ):
        raise InvalidParams(param.name, "opción no válida")
    if param.pattern and raw and not re.fullmatch(param.pattern, raw):
        raise InvalidParams(param.name, "formato no válido")
    return raw


def validate(definition: ToolDefinition, raw: Mapping[str, Any]) -> dict[str, Any]:
    known = {param.name: param for param in definition.params}
    unknown = set(raw) - set(known)
    if unknown:
        raise InvalidParams(sorted(unknown)[0], "parámetro desconocido")
    values: dict[str, Any] = {}
    for name, param in known.items():
        value = raw.get(name, param.default)
        if value is None or value == "" or value == []:
            if param.required:
                raise InvalidParams(name, "es obligatorio")
            values[name] = param.default
            continue
        values[name] = _one(param, value)
    return values


def public_params(definition: ToolDefinition, values: Mapping[str, Any]) -> dict[str, Any]:
    """Los valores secretos no salen del proceso: ni al registro ni a la interfaz."""
    secret = {p.name for p in definition.params if p.kind is ParamKind.SECRET}
    return {k: ("••••" if k in secret and v else v) for k, v in values.items()}

"""Lectura de inventarios de versiones anteriores del esquema."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .inventory import SCHEMA_NAME, SCHEMA_VERSION, Inventory

Document = dict[str, Any]


class UnsupportedSchemaError(ValueError):
    pass


def _from_1_0_0(document: Document) -> Document:
    """2.0.0 añade la identidad del equipo y la posición en su historial."""
    from .identity import UNKNOWN_DEVICE, device_key
    from .inventory import DeviceIdentity

    device = document.get("device")
    key = device_key(DeviceIdentity.model_validate(device)) if device else UNKNOWN_DEVICE
    collection = {
        **document.get("collection", {}),
        "deviceKey": key.value,
        "identityBasis": key.basis.value,
        "sequence": None,
        "previousInventoryId": None,
    }
    return {
        **document,
        "collection": collection,
        "schema": {**document["schema"], "version": "2.0.0"},
    }


def _from_2_0_0(document: Document) -> Document:
    """2.1.0 añade periféricos e impresoras; los inventarios anteriores no los recopilaron."""
    return {
        **document,
        "peripherals": None,
        "schema": {**document["schema"], "version": "2.1.0"},
    }


def _from_2_1_0(document: Document) -> Document:
    """2.2.0 agrupa cada aparato físico y agrega los no conectados. Los campos nuevos tienen
    valor por defecto: un inventario 2.1.0 se lee tal cual, con una fila por función."""
    return {**document, "schema": {**document["schema"], "version": "2.2.0"}}


# Cada entrada transforma un documento de la versión clave a la siguiente versión del esquema.
MIGRATIONS: dict[str, Callable[[Document], Document]] = {
    "1.0.0": _from_1_0_0,
    "2.0.0": _from_2_0_0,
    "2.1.0": _from_2_1_0,
}


def _version_tuple(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError as error:
        raise UnsupportedSchemaError(f"versión de esquema inválida: {version!r}") from error


def upgrade(document: Document) -> Document:
    schema = document.get("schema")
    if not isinstance(schema, dict) or schema.get("name") != SCHEMA_NAME:
        raise UnsupportedSchemaError("el archivo no es un inventario de Honey Check")
    version = schema.get("version")
    if not isinstance(version, str):
        raise UnsupportedSchemaError("el inventario no declara la versión del esquema")
    if _version_tuple(version) > _version_tuple(SCHEMA_VERSION):
        raise UnsupportedSchemaError(
            f"el inventario usa el esquema {version}, más reciente que {SCHEMA_VERSION}"
        )
    while version != SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise UnsupportedSchemaError(f"no hay migración desde el esquema {version}")
        document = step(document)
        version = document["schema"]["version"]
    return document


def load_document(document: Document) -> Inventory:
    return Inventory.model_validate(upgrade(document))

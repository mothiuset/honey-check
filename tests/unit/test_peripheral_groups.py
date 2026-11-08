"""Un aparato físico por fila: los nodos de Windows se agrupan por contenedor y por padre.

Identificadores ficticios: fabricantes y productos 1A2B, seriales y contenedores inventados.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fixtures.devices import all_nodes
from honey_check.domain.inventory import (
    DisconnectedState,
    PeripheralCategory,
    PeripheralConnection,
    PeripheralFunction,
)
from honey_check.domain.peripherals import group_devices
from honey_check.infrastructure.collectors.peripherals import PeripheralsCollector


def by_name(present: bool) -> dict[str, Any]:
    return {g.name: g for g in group_devices(all_nodes()) if g.present is present}


def test_a_composite_keyboard_is_one_device_with_its_functions() -> None:
    kb = by_name(present=True)["Teclado Ficticio K1"]
    assert kb.category is PeripheralCategory.KEYBOARD
    assert kb.connection is PeripheralConnection.USB
    assert kb.functions == (
        PeripheralFunction.KEYBOARD,
        PeripheralFunction.MOUSE,
        PeripheralFunction.MEDIA_KEYS,
    )
    assert len(kb.members) == 8 and not kb.generic_name


def test_receiver_lighting_and_interfaces_join_the_receiver() -> None:
    rx = by_name(present=True)["Receptor Ficticio"]
    assert rx.category is PeripheralCategory.WIRELESS_RECEIVER
    assert PeripheralFunction.LIGHTING in rx.functions and len(rx.members) == 4


def test_built_in_devices_group_by_parent_and_bus_parts_are_left_out() -> None:
    present = by_name(present=True)
    touch = next(g for g in present.values() if g.category is PeripheralCategory.TOUCHPAD)
    assert touch.functions == (PeripheralFunction.TOUCHPAD,)  # su «mouse» es el mismo touchpad
    assert touch.generic_name
    camera = present["Cámara HD"]
    assert camera.functions == (PeripheralFunction.CAMERA, PeripheralFunction.FIRMWARE_UPDATE)
    names = set(present)
    assert "USB Root Hub (USB 3.0)" not in names  # el concentrador no es un periférico
    assert "Audio de pantalla" not in names  # un controlador de audio sin entrada ni salida


def test_external_monitor_is_by_video_cable_and_named_by_its_model() -> None:
    present = by_name(present=True)
    assert present["Pantalla Ficticia 27"].connection is PeripheralConnection.VIDEO
    internal = next(g for g in present.values() if g.name == "Generic PnP Monitor")
    assert internal.connection is PeripheralConnection.INTERNAL


def test_disconnected_are_paired_or_leftovers_and_duplicates_are_marked() -> None:
    tree = SimpleNamespace(nodes=lambda _classes: all_nodes())
    ctx = SimpleNamespace(ports=SimpleNamespace(devices=tree))
    result = PeripheralsCollector()._grouped(ctx, [], {})  # type: ignore[arg-type]  # noqa: SLF001
    assert result is not None
    devices, disconnected = result
    assert {d.name.value for d in devices} >= {"Teclado Ficticio K1", "Receptor Ficticio"}
    states = {d.name: d for d in disconnected}
    phones = states["Audífonos Ficticios"]
    assert phones.state is DisconnectedState.PAIRED
    assert phones.functions == [PeripheralFunction.HEADPHONES]
    old = states["Receptor Ficticio"]
    assert old.state is DisconnectedState.LEFTOVER
    assert old.also_connected  # el mismo receptor está en otro puerto
    assert old.driver_infs == ["oem7.inf"]
    assert disconnected[0].state is DisconnectedState.PAIRED  # emparejados primero


def test_without_device_tree_the_collector_keeps_the_old_list() -> None:
    ctx = SimpleNamespace(ports=SimpleNamespace(devices=None))
    assert PeripheralsCollector()._grouped(ctx, [], {}) is None  # type: ignore[arg-type]  # noqa: SLF001

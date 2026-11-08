"""Árbol de dispositivos ficticio: un teclado compuesto, un receptor conectado y su resto en otro
puerto, lo integrado de un portátil y audífonos Bluetooth emparejados y apagados."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from honey_check.domain.peripherals import COMPUTER_CONTAINER, DeviceNode

KB = "AAAAAAAA-0000-0000-0000-000000000001"
RX = "AAAAAAAA-0000-0000-0000-000000000002"
RX_OLD = "AAAAAAAA-0000-0000-0000-000000000003"
PHONES = "AAAAAAAA-0000-0000-0000-000000000004"
SCREEN = "AAAAAAAA-0000-0000-0000-000000000005"
ROOT_HUB = "USB\\ROOT_HUB30\\4&FICTICIO&0&0"


def node(instance: str, name: str, pnp_class: str, **extra: Any) -> DeviceNode:
    return DeviceNode(instance_id=instance, name=name, pnp_class=pnp_class, **extra)


def keyboard() -> list[DeviceNode]:
    """Un teclado con mouse y teclas multimedia: Windows lo parte en nueve nodos."""
    usb = "USB\\VID_1A2B&PID_0001\\TECLADO01"
    mi0 = "USB\\VID_1A2B&PID_0001&MI_00\\6&F&0&0000"
    mi1 = "USB\\VID_1A2B&PID_0001&MI_01\\6&F&0&0001"
    common = {"container_id": KB, "bus_description": "Teclado Ficticio K1"}
    return [
        node(usb, "USB Composite Device", "USB", parent=ROOT_HUB, **common),
        node(mi0, "USB Input Device", "HIDClass", parent=usb, **common),
        node(mi1, "USB Input Device", "HIDClass", parent=usb, **common),
        node("HID\\VID_1A2B&PID_0001&MI_00\\7&A&0&0000", "HID Keyboard Device", "Keyboard",
             parent=mi0, container_id=KB),
        node("HID\\VID_1A2B&PID_0001&MI_01&COL01\\7&B&0&0000", "HID Keyboard Device",
             "Keyboard", parent=mi1, container_id=KB),
        node("HID\\VID_1A2B&PID_0001&MI_01&COL02\\7&B&0&0001", "HID-compliant mouse", "Mouse",
             parent=mi1, container_id=KB),
        node("HID\\VID_1A2B&PID_0001&MI_01&COL03\\7&B&0&0002",
             "HID-compliant consumer control device", "HIDClass", parent=mi1, container_id=KB),
        node("HID\\VID_1A2B&PID_0001&MI_01&COL04\\7&B&0&0003",
             "HID-compliant vendor-defined device", "HIDClass", parent=mi1, container_id=KB),
    ]  # fmt: skip


def receiver(container: str, port: str, present: bool) -> list[DeviceNode]:
    """Un receptor inalámbrico; su iluminación RGB queda en otros contenedores, colgando de él."""
    usb = f"USB\\VID_1A2B&PID_0002\\5&FICTICIO&0&{port}"
    when = {
        "present": present,
        "last_removal": None if present else datetime(2026, 1, 2, tzinfo=UTC),
    }
    return [
        node(usb, "Receptor Ficticio", "USB", parent=ROOT_HUB, container_id=container,
             bus_description="USB Receiver", driver_inf="oem7.inf", **when),
        node(f"HID\\VID_1A2B&PID_0002&MI_00\\7&{port}&0&0000", "HID Keyboard Device", "Keyboard",
             parent=usb, container_id=container, **when),
        node(f"HID\\VID_1A2B&PID_0002&MI_01\\7&{port}&0&0001", "HID-compliant mouse", "Mouse",
             parent=usb, container_id=container, **when),
        node(f"USB\\VID_1A2B&PID_0002&LAMPARRAY\\6&{port}&1&4_SL", "Receptor Ficticio",
             "HIDClass", parent=usb, container_id=container[:-2] + "9" + port, **when),
    ]  # fmt: skip


def laptop() -> list[DeviceNode]:
    """Lo integrado comparte el contenedor del equipo: se agrupa por padre."""
    touch = "ACPI\\FICT0001\\4&A&0"
    cam = "USB\\VID_1A2B&PID_0003\\0001"
    inside = {"container_id": COMPUTER_CONTAINER}
    return [
        node(touch, "I2C HID Device", "HIDClass", parent="PCI\\VEN_8086&DEV_0001\\3&A&0&A8", **inside),
        node("HID\\FICT0001&COL01\\5&A&0&0000", "HID-compliant mouse", "Mouse", parent=touch, **inside),
        node("HID\\FICT0001&COL02\\5&A&0&0001", "HID-compliant touch pad", "HIDClass",
             parent=touch, **inside),
        node(cam, "USB Composite Device", "USB", parent=ROOT_HUB, bus_description="Cámara HD",
             **inside),
        node("USB\\VID_1A2B&PID_0003&MI_00\\6&C&0&0000", "Cámara HD", "Camera", parent=cam, **inside),
        node("USB\\VID_1A2B&PID_0003&MI_02\\6&C&0&0002", "Camera DFU Device", "USB", parent=cam,
             **inside),
        node(ROOT_HUB, "USB Root Hub (USB 3.0)", "USB", parent="PCI\\VEN_8086&DEV_0002\\3&A&0&A0",
             **inside),
        node("INTELAUDIO\\FUNC_01&VEN_8086\\4&A&0&0201", "Audio de pantalla", "MEDIA", **inside),
        node("ACPI\\FICT0002\\1", "Standard PS/2 Keyboard", "Keyboard", parent="PCI\\X", **inside),
        node("DISPLAY\\FIC0001\\4&A&0&UID1", "Generic PnP Monitor", "Monitor", **inside),
        node("DISPLAY\\FIC0002\\4&A&0&UID2", "Generic Monitor (Pantalla Ficticia 27)", "Monitor",
             container_id=SCREEN),
    ]  # fmt: skip


def headphones() -> list[DeviceNode]:
    """Audífonos emparejados por Bluetooth y apagados: varios servicios, un aparato."""
    off = {
        "present": False,
        "container_id": PHONES,
        "last_removal": datetime(2026, 1, 5, tzinfo=UTC),
    }
    device = "BTHENUM\\DEV_AABBCCDDEEFF\\7&A&0&BLUETOOTHDEVICE_0"
    return [
        node(device, "Audífonos Ficticios", "Bluetooth", parent="BTH\\MS_BTHBRB\\6&A&0&1", **off),
        node("BTHENUM\\{0000110E-0000-1000-8000-00805F9B34FB}_VID&0001_DEV_AABBCCDDEEFF",
             "Audífonos Ficticios Avrcp Transport", "Bluetooth", parent=device, **off),
        node("SWD\\MMDEVAPI\\{0.0.0.00000000}.{FICTICIO}", "Headphones (Audífonos Ficticios)",
             "AudioEndpoint", **off),
    ]  # fmt: skip


def all_nodes() -> list[DeviceNode]:
    return [
        *keyboard(),
        *receiver(RX, "4", present=True),
        *receiver(RX_OLD, "5", present=False),
        *laptop(),
        *headphones(),
    ]

"""Periféricos e impresoras con datos ficticios: identificadores, seriales, IP y conexiones."""

from __future__ import annotations

import pytest

from fakes import FakeCim, FakeRegistry, make_context, make_ports
from honey_check.application.ports import RegistryHive, RegistryView
from honey_check.domain.inventory import PeripheralCategory, PeripheralConnection, PrinterConnection
from honey_check.domain.peripherals import (
    driver_version_text,
    ip_in,
    parse_instance_id,
    printer_connection,
)
from honey_check.infrastructure.collectors.peripherals import PeripheralsCollector

HKLM = RegistryHive.LOCAL_MACHINE
VIEW = RegistryView.DEFAULT


@pytest.mark.parametrize(
    ("instance", "connection", "vid", "pid", "serial"),
    [
        (
            "USB\\VID_046D&PID_C52B\\SERIE0001",
            PeripheralConnection.USB,
            "046D",
            "C52B",
            "SERIE0001",
        ),
        # Último segmento generado por Windows: no es un serial.
        ("USB\\VID_046D&PID_C52B\\5&2B1D3F1&0&2", PeripheralConnection.USB, "046D", "C52B", None),
        (
            "HID\\VID_046D&PID_C53F&MI_00\\7&B773533&0&0000",
            PeripheralConnection.USB,
            "046D",
            "C53F",
            None,
        ),
        ("HID\\FICT7863&COL01\\5&E50357C&0&0000", PeripheralConnection.INTERNAL, None, None, None),
        (
            "USBSTOR\\DISK&VEN_FICT&PROD_USB&REV_1.00\\AA0011223344&0",
            PeripheralConnection.USB,
            None,
            None,
            "AA0011223344",
        ),
        (
            "BTHENUM\\{0000110B-0000-1000-8000-00805F9B34FB}_VID&0002046D_PID&B33E\\7&1A&0&AABBCCDDEEFF_C00000000",
            PeripheralConnection.BLUETOOTH,
            None,
            None,
            "AA:BB:CC:DD:EE:FF",
        ),
        ("ACPI\\FICT51A0\\1", PeripheralConnection.INTERNAL, None, None, None),
        ("SWD\\MMDEVAPI\\{0.0.0.00000000}", PeripheralConnection.VIRTUAL, None, None, None),
        (None, PeripheralConnection.OTHER, None, None, None),
    ],
)
def test_instance_ids(
    instance: str | None,
    connection: PeripheralConnection,
    vid: str | None,
    pid: str | None,
    serial: str | None,
) -> None:
    parsed = parse_instance_id(instance)
    assert (parsed.connection, parsed.vendor_id, parsed.product_id, parsed.serial) == (
        connection,
        vid,
        pid,
        serial,
    )


@pytest.mark.parametrize(
    ("port", "driver", "network", "tcp", "expected"),
    [
        ("IP_10.0.0.20", "Impresora Ficticia PCL", False, True, PrinterConnection.NETWORK_TCP),
        ("WSD-1234-abcd", "Impresora Ficticia", False, False, PrinterConnection.WSD),
        ("USB001", "Impresora Ficticia", False, False, PrinterConnection.USB),
        ("\\\\SERVIDOR\\Ficticia", "Impresora Ficticia", True, False, PrinterConnection.SHARED),
        ("PORTPROMPT:", "Microsoft Print To PDF", False, False, PrinterConnection.VIRTUAL),
        ("LPT1:", "Impresora Ficticia", False, False, PrinterConnection.LOCAL_OTHER),
        (
            "https://impresion.ficticia/ipp",
            "Microsoft IPP Class Driver",
            False,
            False,
            PrinterConnection.IPP,
        ),
    ],
)
def test_printer_connection(
    port: str, driver: str, network: bool, tcp: bool, expected: PrinterConnection
) -> None:
    assert printer_connection(port, driver, is_network_queue=network, has_tcp_port=tcp) is expected


def test_helpers() -> None:
    assert ip_in("http://10.1.2.3:80/wsd") == "10.1.2.3"
    assert ip_in("999.1.2.3") is None
    assert driver_version_text((10 << 48) | (0 << 32) | (26100 << 16) | 4484) == "10.0.26100.4484"
    assert driver_version_text(0) is None


def scan(cim: FakeCim, registry: FakeRegistry | None = None):  # type: ignore[no-untyped-def]
    ctx = make_context(make_ports(cim=cim, registry=registry), module="peripherals")
    return PeripheralsCollector().collect(ctx), ctx


def test_devices_with_serial_from_the_usb_parent() -> None:
    cim = FakeCim(
        {
            "Win32_PnPEntity": [
                {
                    "Name": "Lector Ficticio",
                    "PNPClass": "SmartCardReader",
                    "Manufacturer": "Ficticia",
                    "PNPDeviceID": "USB\\VID_096E&PID_0608\\5&1&0&1",
                    "Status": "OK",
                    "ConfigManagerErrorCode": 0,
                },
                {
                    "Name": "Token Ficticio",
                    "PNPClass": "USB",
                    "PNPDeviceID": "USB\\VID_096E&PID_0608\\TOKEN123",
                    "Status": "OK",
                    "ConfigManagerErrorCode": 0,
                },
                {
                    "Name": "Teclado Ficticio",
                    "PNPClass": "Keyboard",
                    "PNPDeviceID": "HID\\VID_046D&PID_C31C&MI_00\\7&1&0&0000",
                    "Status": "Error",
                    "ConfigManagerErrorCode": 28,
                },
                {
                    "Name": "Generic USB Hub",
                    "PNPClass": "USB",
                    "PNPDeviceID": "USB\\VID_05E3&PID_0610\\6&1&0&1",
                    "Status": "OK",
                    "ConfigManagerErrorCode": 0,
                },
                {
                    "Name": "Audio interno",
                    "PNPClass": "MEDIA",
                    "PNPDeviceID": "HDAUDIO\\FUNC_01\\4&1",
                    "Status": "OK",
                    "ConfigManagerErrorCode": 0,
                },
                {
                    "Name": "Memoria USB Ficticia",
                    "PNPClass": "DiskDrive",
                    "PNPDeviceID": "USBSTOR\\DISK&VEN_FICT&PROD_X\\SERIEUSB99&0",
                    "Status": "OK",
                    "ConfigManagerErrorCode": 0,
                },
                {
                    "Name": "Disco interno",
                    "PNPClass": "DiskDrive",
                    "PNPDeviceID": "SCSI\\DISK&VEN_NVME\\5&1",
                    "Status": "OK",
                    "ConfigManagerErrorCode": 0,
                },
            ],
            "Win32_PnPSignedDriver": [
                {
                    "DeviceID": "USB\\VID_096E&PID_0608\\5&1&0&1",
                    "DriverVersion": "1.2.3.4",
                    "DriverProviderName": "Ficticia",
                    "DriverDate": "2024-01-02T00:00:00.000000Z",
                }
            ],
        }
    )
    section, ctx = scan(cim)
    by_name = {d.name.value: d for d in section.devices}
    reader = by_name["Lector Ficticio"]
    assert reader.category is PeripheralCategory.SMART_CARD_READER
    assert reader.serial_number.value == "TOKEN123"  # tomado del nodo USB principal
    assert reader.vendor_name.value == "Feitian"
    assert reader.driver_version.value == "1.2.3.4"
    assert by_name["Teclado Ficticio"].error_description is not None
    assert by_name["Memoria USB Ficticia"].category is PeripheralCategory.USB_STORAGE
    assert by_name["Memoria USB Ficticia"].serial_number.value == "SERIEUSB99"
    # Concentradores, audio interno y discos internos no son periféricos conectados.
    assert {"Generic USB Hub", "Audio interno", "Disco interno"}.isdisjoint(by_name)
    assert ctx.errors == []


def test_printers_with_ip_usb_serial_wsd_and_queue() -> None:
    cim = FakeCim(
        {
            "Win32_Printer": [
                {
                    "Name": "Oficina Red",
                    "PortName": "IP_10.0.0.20",
                    "DriverName": "Ficticia PCL6",
                    "Default": True,
                    "PrinterStatus": 3,
                    "DetectedErrorState": 5,
                },
                {
                    "Name": "Recepción USB",
                    "PortName": "USB001",
                    "DriverName": "Ficticia USB",
                    "PrinterStatus": 3,
                },
                {
                    "Name": "Sala WSD",
                    "PortName": "WSD-1234",
                    "DriverName": "Ficticia WSD",
                    "WorkOffline": True,
                },
                {
                    "Name": "Microsoft Print to PDF",
                    "PortName": "PORTPROMPT:",
                    "DriverName": "Microsoft Print To PDF",
                    "PrinterStatus": 3,
                },
            ],
            "Win32_TCPIPPrinterPort": [
                {
                    "Name": "IP_10.0.0.20",
                    "HostAddress": "10.0.0.20",
                    "PortNumber": 9100,
                    "Protocol": 1,
                }
            ],
            "MSFT_PrinterDriver": [
                {
                    "Name": "Ficticia PCL6",
                    "Manufacturer": "Ficticia",
                    "DriverVersion": (6 << 48) | (1 << 32) | (2 << 16) | 3,
                }
            ],
            "Win32_PrintJob": [{"Name": "Oficina Red, 4"}, {"Name": "Oficina Red, 5"}],
        }
    )
    registry = FakeRegistry()
    usbprint = (
        r"SYSTEM\CurrentControlSet\Control\DeviceClasses\{28d78fad-5a12-11d1-ae5b-0000f803a8c2}"
    )
    name = "##?#USB#VID_04B8&PID_0005#IMPSERIE77#{28d78fad-5a12-11d1-ae5b-0000f803a8c2}"
    registry.put(
        HKLM,
        VIEW,
        f"{usbprint}\\{name}\\#\\Device Parameters",
        {"Port Number": 1, "Base Name": "USB"},
    )
    registry.put(
        HKLM,
        VIEW,
        r"SYSTEM\CurrentControlSet\Enum\SWD\DAFWSDProvider\uuid-ficticio",
        {"FriendlyName": "Sala WSD", "LocationInformation": "http://10.0.0.33:80/wsd"},
    )
    section, _ = scan(cim, registry)
    printers = {p.name: p for p in section.printers}
    office = printers["Oficina Red"]
    assert section.default_printer == "Oficina Red"
    assert (office.connection, office.host_address.value, office.port_number.value) == (
        PrinterConnection.NETWORK_TCP,
        "10.0.0.20",
        9100,
    )
    assert office.protocol.value == "RAW"
    assert office.manufacturer.value == "Ficticia"
    assert office.driver_version.value == "6.1.2.3"
    assert office.detected_error.value == "low_toner"
    assert office.queued_jobs.value == 2
    assert office.serial_number.reason == "requires_snmp_query"
    usb = printers["Recepción USB"]
    assert (usb.connection, usb.serial_number.value, usb.usb_vendor_id) == (
        PrinterConnection.USB,
        "IMPSERIE77",
        "04B8",
    )
    wsd = printers["Sala WSD"]
    assert (wsd.connection, wsd.host_address.value, wsd.status.value) == (
        PrinterConnection.WSD,
        "10.0.0.33",
        "offline",
    )
    assert printers["Microsoft Print to PDF"].connection is PrinterConnection.VIRTUAL
    # La predeterminada primero y las virtuales al final.
    assert section.printers[0].name == "Oficina Red"
    assert section.printers[-1].connection is PrinterConnection.VIRTUAL

"""Periféricos conectados e impresoras instaladas.

Fuentes: el árbol de dispositivos de cfgmgr32 (cada aparato físico con todas sus funciones, y los
que Windows recuerda sin estar conectados), Win32_PnPEntity (estado de lo conectado; también es la
alternativa si el árbol no se puede leer), Win32_PnPSignedDriver (driver), Win32_Printer,
Win32_TCPIPPrinterPort (IP de impresoras de red), MSFT_PrinterDriver (fabricante del driver),
Win32_PrintJob (cola) y el Registro (puertos USB de impresión y ubicación de impresoras WSD).
El serial y los consumibles de una impresora de red se leen aparte, por SNMP y a pedido del técnico.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from honey_check.application.collection import CollectionContext, ModuleFailed
from honey_check.application.ports import (
    CimQuery,
    RegistryAccessDenied,
    RegistryHive,
    RegistryKeyMissing,
    RegistryView,
)
from honey_check.domain.classification import DEVICE_ERRORS
from honey_check.domain.inventory import (
    DisconnectedPeripheral,
    DisconnectedState,
    Peripheral,
    PeripheralCategory,
    PeripheralConnection,
    PeripheralFunction,
    PeripheralPart,
    PeripheralsSection,
    Printer,
    PrinterConnection,
)
from honey_check.domain.normalize import (
    clean_text,
    observed_bool,
    observed_datetime,
    observed_positive_int,
    observed_text,
)
from honey_check.domain.observed import Observed, Reason
from honey_check.domain.peripherals import (
    EXTERNAL_ONLY,
    PERIPHERAL_CLASSES,
    PRINTER_ERRORS,
    PRINTER_STATUS,
    DeviceGroup,
    DeviceNode,
    category_of,
    driver_version_text,
    group_devices,
    ip_in,
    is_bus_infrastructure,
    parse_instance_id,
    printer_connection,
    same_device,
)
from honey_check.domain.usb_vendors import vendor_name

log = logging.getLogger(__name__)

_ROOT = "root/cimv2"
_STD = "root/StandardCimv2"

_PNP_CLASSES = PERIPHERAL_CLASSES
_PNP = CimQuery(
    _ROOT,
    "Win32_PnPEntity",
    ("Name", "PNPClass", "Manufacturer", "PNPDeviceID", "Status", "ConfigManagerErrorCode"),
    where=" OR ".join(f"PNPClass='{name}'" for name in _PNP_CLASSES),
)
_DRIVERS = CimQuery(
    _ROOT,
    "Win32_PnPSignedDriver",
    ("DeviceID", "DriverVersion", "DriverDate", "DriverProviderName"),
    where=" OR ".join(f"DeviceClass='{name.upper()}'" for name in _PNP_CLASSES),
)
_PRINTERS = CimQuery(
    _ROOT,
    "Win32_Printer",
    (
        "Name",
        "PortName",
        "DriverName",
        "Network",
        "Shared",
        "ShareName",
        "Default",
        "WorkOffline",
        "PrinterStatus",
        "DetectedErrorState",
        "Location",
        "Comment",
    ),
)
_TCP_PORTS = CimQuery(
    _ROOT, "Win32_TCPIPPrinterPort", ("Name", "HostAddress", "PortNumber", "Protocol")
)
_PRINTER_DRIVERS = CimQuery(_STD, "MSFT_PrinterDriver", ("Name", "Manufacturer", "DriverVersion"))
_JOBS = CimQuery(_ROOT, "Win32_PrintJob", ("Name",))

# Interfaz de dispositivo de usbprint: cada instancia anota su puerto (USB001…).
_USBPRINT_CLASS = (
    r"SYSTEM\CurrentControlSet\Control\DeviceClasses\{28d78fad-5a12-11d1-ae5b-0000f803a8c2}"
)
_WSD_ENUM = r"SYSTEM\CurrentControlSet\Enum\SWD\DAFWSDProvider"
_MAX_REGISTRY_ENTRIES = 200

_PROTOCOLS = {1: "RAW", 2: "LPR"}


def _registry_children(ctx: CollectionContext, path: str) -> list[str]:
    try:
        return ctx.ports.registry.subkeys(RegistryHive.LOCAL_MACHINE, path, RegistryView.DEFAULT)[
            :_MAX_REGISTRY_ENTRIES
        ]
    except (RegistryKeyMissing, RegistryAccessDenied, OSError):
        return []


def _registry_values(ctx: CollectionContext, path: str) -> dict[str, Any]:
    try:
        return ctx.ports.registry.values(RegistryHive.LOCAL_MACHINE, path, RegistryView.DEFAULT)
    except (RegistryKeyMissing, RegistryAccessDenied, OSError):
        return {}


def usb_print_ports(ctx: CollectionContext) -> dict[str, tuple[str | None, str | None, str | None]]:
    """Puerto (USB001) → VID, PID y serial de la impresora USB que lo creó."""
    ports: dict[str, tuple[str | None, str | None, str | None]] = {}
    for name in _registry_children(ctx, _USBPRINT_CLASS):
        params = _registry_values(ctx, f"{_USBPRINT_CLASS}\\{name}\\#\\Device Parameters")
        number = params.get("Port Number")
        base = clean_text(params.get("Base Name")) or "USB"
        if not isinstance(number, int):
            continue
        instance = name.lstrip("#?").replace("#", "\\")
        instance = instance.rsplit("\\{", 1)[0]
        parsed = parse_instance_id(instance)
        ports[f"{base}{number:03d}".upper()] = (parsed.vendor_id, parsed.product_id, parsed.serial)
    return ports


def wsd_addresses(ctx: CollectionContext) -> dict[str, str]:
    """Nombre de la impresora WSD → dirección IP anunciada por el dispositivo."""
    found: dict[str, str] = {}
    for name in _registry_children(ctx, _WSD_ENUM):
        values = _registry_values(ctx, f"{_WSD_ENUM}\\{name}")
        friendly = clean_text(values.get("FriendlyName"))
        address = ip_in(clean_text(values.get("LocationInformation")))
        if friendly and address:
            found[friendly.lower()] = address
    return found


def _jobs_per_printer(rows: Iterable[Mapping[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for row in rows:
        name = clean_text(row.get("Name"))
        if name and "," in name:
            counter[name.rsplit(",", 1)[0].strip().lower()] += 1
    return counter


class PeripheralsCollector:
    name = "peripherals"
    timeout_s = 45.0

    def collect(self, ctx: CollectionContext) -> PeripheralsSection:
        pnp_r, drivers_r, printers_r, ports_r, printer_drivers_r, jobs_r = ctx.query(
            [_PNP, _DRIVERS, _PRINTERS, _TCP_PORTS, _PRINTER_DRIVERS, _JOBS],
            optional=[_DRIVERS, _TCP_PORTS, _PRINTER_DRIVERS, _JOBS],
        )
        if not pnp_r.ok and not printers_r.ok:
            raise ModuleFailed(
                "query_failed", "No se pudieron consultar periféricos ni impresoras", _PNP.source
            )
        drivers = {
            str(row.get("DeviceID") or "").upper(): row
            for row in drivers_r.rows
            if row.get("DeviceID")
        }
        grouped = self._grouped(ctx, pnp_r.rows, drivers)
        devices, disconnected = grouped or (self._devices(pnp_r.rows, drivers), [])
        printers = self._printers(
            ctx, printers_r.rows, ports_r.rows, printer_drivers_r.rows, jobs_r.rows
        )
        default = next((p.name for p in printers if p.is_default.value), None)
        return PeripheralsSection(
            printers=printers,
            devices=devices,
            default_printer=default,
            disconnected=disconnected,
        )

    # --- Aparatos físicos ---------------------------------------------------------------------

    def _grouped(
        self,
        ctx: CollectionContext,
        rows: Iterable[Mapping[str, Any]],
        drivers: dict[str, Mapping[str, Any]],
    ) -> tuple[list[Peripheral], list[DisconnectedPeripheral]] | None:
        tree = ctx.ports.devices
        if tree is None:
            return None
        try:
            nodes = tree.nodes(_PNP_CLASSES)
        except Exception as error:  # noqa: BLE001 - sin árbol se usa la lista de WMI
            log.info("Árbol de dispositivos no disponible: %s", type(error).__name__)
            return None
        if not nodes:
            return None
        wmi = {str(row.get("PNPDeviceID") or "").upper(): row for row in rows}
        groups = group_devices(nodes)
        present = [group for group in groups if group.present]
        devices = [self._peripheral(group, wmi, drivers) for group in present]
        order = list(PeripheralCategory)
        devices.sort(key=lambda d: (order.index(d.category), (d.name.value or "").lower()))
        return devices, self._disconnected([g for g in groups if not g.present], present)

    @staticmethod
    def _peripheral(
        group: DeviceGroup,
        wmi: Mapping[str, Mapping[str, Any]],
        drivers: Mapping[str, Mapping[str, Any]],
    ) -> Peripheral:
        main = group.main_member
        row = wmi.get(main.instance_id.upper()) or wmi.get(group.root.instance_id.upper()) or {}
        driver = drivers.get(main.instance_id.upper(), {})
        codes = [
            int((wmi.get(node.instance_id.upper()) or {}).get("ConfigManagerErrorCode") or 0)
            or node.problem_code
            for node in group.members
        ]
        code = next((value for value in codes if value), 0)
        hardware = group.hardware
        serial = next(
            (
                parsed.serial
                for node in group.members
                if (parsed := parse_instance_id(node.instance_id)).serial
            ),
            None,
        )
        vendor = vendor_name(hardware.vendor_id)
        source = "cfgmgr32:DEVPKEY_Device_ContainerId"
        return Peripheral(
            name=observed_text(group.name, source),
            category=group.category,
            connection=group.connection,
            manufacturer=observed_text(
                row.get("Manufacturer") or main.manufacturer, f"{_PNP.source}.Manufacturer"
            ),
            vendor_name=(
                Observed[str].inferred(vendor, "usb-ids:VID")
                if vendor
                else Observed[str].unknown(Reason.NOT_REPORTED, "usb-ids:VID")
            ),
            vendor_id=hardware.vendor_id,
            product_id=hardware.product_id,
            serial_number=(
                Observed[str].reported(serial, "cfgmgr32:InstanceId")
                if serial
                else Observed[str].unknown(Reason.NOT_REPORTED, "cfgmgr32:InstanceId")
            ),
            instance_id=group.root.instance_id,
            driver_provider=observed_text(
                driver.get("DriverProviderName"), f"{_DRIVERS.source}.DriverProviderName"
            ),
            driver_version=observed_text(
                driver.get("DriverVersion"), f"{_DRIVERS.source}.DriverVersion"
            ),
            driver_date=observed_datetime(
                driver.get("DriverDate"), f"{_DRIVERS.source}.DriverDate"
            ),
            status=observed_text(row.get("Status") or ("Error" if code else "OK"), _PNP.source),
            error_code=code,
            error_description=DEVICE_ERRORS.get(code) if code else None,
            generic_name=group.generic_name,
            functions=list(group.functions),
            container_id=group.container_id,
            last_connected_at=group.last_arrival,
            parts=[_part(node) for node in group.members],
        )

    @staticmethod
    def _disconnected(
        groups: list[DeviceGroup], present: list[DeviceGroup]
    ) -> list[DisconnectedPeripheral]:
        connected_ids = {
            (group.hardware.vendor_id, group.hardware.product_id)
            for group in present
            if group.hardware.vendor_id
        }
        connected_names = {
            (group.name or "").lower() for group in present if not group.generic_name
        }
        merged: dict[tuple[str, str, bool], list[DeviceGroup]] = {}
        for group in groups:
            merged.setdefault(same_device(group), []).append(group)
        found: list[DisconnectedPeripheral] = []
        for same in merged.values():
            first = same[0]
            functions = [f for f in PeripheralFunction if any(f in g.functions for g in same)]
            seen = [g.last_removal or g.last_arrival for g in same]
            dates = [date for date in seen if date]
            hardware = first.hardware
            found.append(
                DisconnectedPeripheral(
                    name=first.name,
                    generic_name=first.generic_name,
                    category=first.category,
                    connection=first.connection,
                    functions=functions,
                    state=(
                        DisconnectedState.PAIRED
                        if first.is_bluetooth_device
                        else DisconnectedState.LEFTOVER
                    ),
                    vendor_id=hardware.vendor_id,
                    product_id=hardware.product_id,
                    vendor_name=vendor_name(hardware.vendor_id),
                    container_id=first.container_id,
                    last_seen_at=max(dates) if dates else None,
                    also_connected=(hardware.vendor_id, hardware.product_id) in connected_ids
                    or (not first.generic_name and (first.name or "").lower() in connected_names),
                    driver_infs=sorted({inf for g in same for inf in g.driver_infs}),
                    parts=[_part(node) for g in same for node in g.members],
                )
            )
        far_past = datetime.min.replace(tzinfo=UTC)
        return sorted(
            found,
            key=lambda d: (
                d.state is not DisconnectedState.PAIRED,
                -(d.last_seen_at or far_past).timestamp(),
            ),
        )

    # --- Dispositivos (alternativa sin árbol) --------------------------------------------------

    @staticmethod
    def _devices(
        rows: Iterable[Mapping[str, Any]], drivers: dict[str, Mapping[str, Any]]
    ) -> list[Peripheral]:
        rows = list(rows)
        # El serial de un dispositivo compuesto está en su nodo USB principal, no en sus funciones.
        serials: dict[tuple[str, str], str] = {}
        for row in rows:
            parsed = parse_instance_id(clean_text(row.get("PNPDeviceID")))
            if parsed.serial and parsed.vendor_id and parsed.product_id:
                serials.setdefault((parsed.vendor_id, parsed.product_id), parsed.serial)

        source = _PNP.source
        devices: list[Peripheral] = []
        for row in rows:
            instance = clean_text(row.get("PNPDeviceID"))
            name = clean_text(row.get("Name"))
            category = category_of(clean_text(row.get("PNPClass")), instance)
            if category is None or is_bus_infrastructure(name):
                continue
            parsed = parse_instance_id(instance)
            external = parsed.connection in (
                PeripheralConnection.USB,
                PeripheralConnection.BLUETOOTH,
            )
            if category in EXTERNAL_ONLY and not external:
                continue
            serial = parsed.serial or (
                serials.get((parsed.vendor_id, parsed.product_id))
                if parsed.vendor_id and parsed.product_id
                else None
            )
            driver = drivers.get((instance or "").upper(), {})
            code = int(row.get("ConfigManagerErrorCode") or 0)
            vendor = vendor_name(parsed.vendor_id)
            devices.append(
                Peripheral(
                    name=observed_text(name, f"{source}.Name"),
                    category=category,
                    connection=parsed.connection,
                    manufacturer=observed_text(row.get("Manufacturer"), f"{source}.Manufacturer"),
                    vendor_name=(
                        Observed[str].inferred(vendor, "usb-ids:VID")
                        if vendor
                        else Observed[str].unknown(Reason.NOT_REPORTED, "usb-ids:VID")
                    ),
                    vendor_id=parsed.vendor_id,
                    product_id=parsed.product_id,
                    serial_number=(
                        Observed[str].reported(serial, f"{source}.PNPDeviceID")
                        if serial
                        else Observed[str].unknown(Reason.NOT_REPORTED, f"{source}.PNPDeviceID")
                    ),
                    instance_id=instance,
                    driver_provider=observed_text(
                        driver.get("DriverProviderName"), f"{_DRIVERS.source}.DriverProviderName"
                    ),
                    driver_version=observed_text(
                        driver.get("DriverVersion"), f"{_DRIVERS.source}.DriverVersion"
                    ),
                    driver_date=observed_datetime(
                        driver.get("DriverDate"), f"{_DRIVERS.source}.DriverDate"
                    ),
                    status=observed_text(row.get("Status"), f"{source}.Status"),
                    error_code=code,
                    error_description=DEVICE_ERRORS.get(code) if code else None,
                )
            )
        order = list(PeripheralCategory)
        return sorted(
            devices, key=lambda d: (order.index(d.category), (d.name.value or "").lower())
        )

    # --- Impresoras ---------------------------------------------------------------------------

    def _printers(
        self,
        ctx: CollectionContext,
        rows: Iterable[Mapping[str, Any]],
        tcp_rows: Iterable[Mapping[str, Any]],
        driver_rows: Iterable[Mapping[str, Any]],
        job_rows: Iterable[Mapping[str, Any]],
    ) -> list[Printer]:
        rows = list(rows)
        if not rows:
            return []
        tcp = {str(row.get("Name") or "").lower(): row for row in tcp_rows}
        drivers = {str(row.get("Name") or "").lower(): row for row in driver_rows}
        jobs = _jobs_per_printer(job_rows)
        usb_ports = usb_print_ports(ctx)
        wsd = wsd_addresses(ctx)
        source = _PRINTERS.source
        printers: list[Printer] = []
        for row in rows:
            name = clean_text(row.get("Name"))
            if not name:
                continue
            port = clean_text(row.get("PortName"))
            driver_name = clean_text(row.get("DriverName"))
            tcp_port = tcp.get((port or "").lower())
            connection = printer_connection(
                port,
                driver_name,
                is_network_queue=bool(row.get("Network")),
                has_tcp_port=tcp_port is not None,
            )
            driver = drivers.get((driver_name or "").lower(), {})
            usb = (
                usb_ports.get((port or "").upper()) if connection is PrinterConnection.USB else None
            )
            printers.append(
                Printer(
                    name=name,
                    driver_name=observed_text(driver_name, f"{source}.DriverName"),
                    manufacturer=observed_text(
                        driver.get("Manufacturer"), f"{_PRINTER_DRIVERS.source}.Manufacturer"
                    ),
                    driver_version=(
                        Observed[str].reported(version, f"{_PRINTER_DRIVERS.source}.DriverVersion")
                        if (version := driver_version_text(driver.get("DriverVersion")))
                        else Observed[str].unknown(Reason.NOT_REPORTED, _PRINTER_DRIVERS.source)
                    ),
                    port_name=observed_text(port, f"{source}.PortName"),
                    connection=connection,
                    host_address=self._address(connection, port, tcp_port, wsd.get(name.lower())),
                    port_number=observed_positive_int(
                        tcp_port.get("PortNumber") if tcp_port else None,
                        f"{_TCP_PORTS.source}.PortNumber",
                    ),
                    protocol=(
                        Observed[str].reported(_PROTOCOLS[proto], f"{_TCP_PORTS.source}.Protocol")
                        if tcp_port and (proto := tcp_port.get("Protocol")) in _PROTOCOLS
                        else Observed[str].unknown(
                            Reason.NOT_APPLICABLE, f"{_TCP_PORTS.source}.Protocol"
                        )
                    ),
                    is_default=observed_bool(row.get("Default"), f"{source}.Default"),
                    is_shared=observed_bool(row.get("Shared"), f"{source}.Shared"),
                    share_name=observed_text(row.get("ShareName"), f"{source}.ShareName"),
                    status=self._status(row),
                    detected_error=(
                        Observed[str].reported(error, f"{source}.DetectedErrorState")
                        if (error := PRINTER_ERRORS.get(int(row.get("DetectedErrorState") or 0)))
                        else Observed[str].unknown(
                            Reason.NOT_REPORTED, f"{source}.DetectedErrorState"
                        )
                    ),
                    location=observed_text(row.get("Location"), f"{source}.Location"),
                    comment=observed_text(row.get("Comment"), f"{source}.Comment"),
                    serial_number=(
                        Observed[str].reported(usb[2], f"registry:HKLM\\{_USBPRINT_CLASS}")
                        if usb and usb[2]
                        else Observed[str].unknown(
                            Reason.NOT_REPORTED
                            if connection is not PrinterConnection.NETWORK_TCP
                            else "requires_snmp_query",
                            "printer",
                        )
                    ),
                    usb_vendor_id=usb[0] if usb else None,
                    usb_product_id=usb[1] if usb else None,
                    queued_jobs=Observed[int].reported(jobs.get(name.lower(), 0), _JOBS.source),
                )
            )
        return sorted(
            printers,
            key=lambda p: (
                not p.is_default.value,
                p.connection is PrinterConnection.VIRTUAL,
                p.name.lower(),
            ),
        )

    @staticmethod
    def _address(
        connection: PrinterConnection,
        port: str | None,
        tcp_port: Mapping[str, Any] | None,
        wsd_address: str | None,
    ) -> Observed[str]:
        if tcp_port and clean_text(tcp_port.get("HostAddress")):
            return Observed[str].reported(
                str(tcp_port["HostAddress"]).strip(), f"{_TCP_PORTS.source}.HostAddress"
            )
        if connection is PrinterConnection.WSD and wsd_address:
            return Observed[str].reported(
                wsd_address, f"registry:HKLM\\{_WSD_ENUM}.LocationInformation"
            )
        if connection is PrinterConnection.SHARED and port and port.startswith("\\\\"):
            return Observed[str].reported(port.split("\\")[2], f"{_PRINTERS.source}.PortName")
        if (address := ip_in(port)) is not None:
            return Observed[str].inferred(address, f"{_PRINTERS.source}.PortName")
        return Observed[str].unknown(Reason.NOT_APPLICABLE, f"{_PRINTERS.source}.PortName")

    @staticmethod
    def _status(row: Mapping[str, Any]) -> Observed[str]:
        source = f"{_PRINTERS.source}.PrinterStatus"
        if row.get("WorkOffline"):
            return Observed[str].reported("offline", f"{_PRINTERS.source}.WorkOffline")
        status = PRINTER_STATUS.get(int(row.get("PrinterStatus") or 0))
        if status is None:
            return Observed[str].unknown(Reason.NOT_REPORTED, source)
        return Observed[str].reported(status, source)


def _part(node: DeviceNode) -> PeripheralPart:
    return PeripheralPart(
        instance_id=node.instance_id,
        name=node.name,
        pnp_class=node.pnp_class,
        present=node.present,
        driver_inf=node.driver_inf,
    )

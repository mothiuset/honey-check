"""Interpretación de periféricos e impresoras a partir de los identificadores de Windows.

Solo texto: sin llamadas al sistema. Un identificador de instancia como
`USB\\VID_046D&PID_C52B\\1234ABCD` aporta fabricante, producto y, si el último segmento no lo
generó Windows (no contiene `&`), el número de serie real del dispositivo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from .inventory import (
    PeripheralCategory,
    PeripheralConnection,
    PeripheralFunction,
    PrinterConnection,
)

_VID_PID = re.compile(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", re.IGNORECASE)
# BTHENUM\DEV_<dirección>\… o BTHLE\DEV_<dirección>\…&<dirección>: la dirección va seguida de
# «_», «\» o del final.
_BT_ADDRESS = re.compile(r"(?:DEV_|[_&])([0-9A-F]{12})(?=_|\\|$)", re.IGNORECASE)
_USBSTOR_SERIAL = re.compile(r"^USBSTOR\\[^\\]+\\([^\\&]+)&\d+$", re.IGNORECASE)
_IP = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


@dataclass(frozen=True)
class DeviceNode:
    """Un nodo del árbol de dispositivos de Windows, conectado o no. Un aparato físico (un teclado
    con teclas multimedia, un receptor inalámbrico) son varios nodos con el mismo contenedor."""

    instance_id: str
    name: str | None
    pnp_class: str | None
    manufacturer: str | None = None
    container_id: str | None = None
    parent: str | None = None
    bus_description: str | None = None  # el nombre que el propio aparato reporta
    present: bool = True
    problem_code: int = 0
    driver_inf: str | None = None
    last_arrival: datetime | None = None
    last_removal: datetime | None = None
    # Identificadores con los que Windows busca su controlador (del más al menos específico).
    hardware_ids: tuple[str, ...] = ()
    compatible_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class HardwareId:
    connection: PeripheralConnection
    vendor_id: str | None = None
    product_id: str | None = None
    serial: str | None = None


def _usb_serial(instance: str) -> str | None:
    """El último segmento es el serial salvo que Windows lo haya generado (contiene `&`)."""
    parts = instance.split("\\")
    if len(parts) < 3:
        return None
    last = parts[-1]
    if not last or "&" in last or len(last) < 4 or set(last) <= {"0"}:
        return None
    return last


def parse_instance_id(instance: str | None) -> HardwareId:
    if not instance:
        return HardwareId(PeripheralConnection.OTHER)
    upper = instance.upper()
    bus = upper.split("\\", 1)[0]
    if bus.startswith(("BTHENUM", "BTHLE", "BTH", "BTHLEDEVICE")):
        address = _BT_ADDRESS.search(upper.split("\\", 1)[-1])
        mac = ":".join(address.group(1)[i : i + 2] for i in range(0, 12, 2)) if address else None
        match = _VID_PID.search(upper)
        return HardwareId(
            PeripheralConnection.BLUETOOTH,
            match.group(1) if match else None,
            match.group(2) if match else None,
            mac if mac and mac != "00:00:00:00:00:00" else None,
        )
    if bus == "USBSTOR":
        stored = _USBSTOR_SERIAL.match(instance)
        return HardwareId(PeripheralConnection.USB, serial=stored.group(1) if stored else None)
    match = _VID_PID.search(upper)
    if bus == "HID" and not match:
        return HardwareId(PeripheralConnection.INTERNAL)  # touchpads y teclados por I2C o SPI
    if bus in ("USB", "HID", "USBPRINT", "WPDBUSENUMROOT") or (match and bus not in ("PCI",)):
        serial = _usb_serial(instance) if bus == "USB" and "&MI_" not in upper else None
        return HardwareId(
            PeripheralConnection.USB if match or bus == "USB" else PeripheralConnection.OTHER,
            match.group(1) if match else None,
            match.group(2) if match else None,
            serial,
        )
    if bus in ("SWD", "ROOT", "SW"):
        return HardwareId(PeripheralConnection.VIRTUAL)
    if bus in ("ACPI", "PCI", "HDAUDIO", "INTELAUDIO", "DISPLAY", "I2C", "UEFI", "STORAGE", "SCSI"):
        return HardwareId(PeripheralConnection.INTERNAL)
    return HardwareId(PeripheralConnection.OTHER)


_CATEGORIES = {
    "KEYBOARD": PeripheralCategory.KEYBOARD,
    "MOUSE": PeripheralCategory.MOUSE,
    "CAMERA": PeripheralCategory.CAMERA,
    "IMAGE": PeripheralCategory.IMAGING,
    "MEDIA": PeripheralCategory.AUDIO,
    "AUDIOENDPOINT": PeripheralCategory.AUDIO_ENDPOINT,
    "BLUETOOTH": PeripheralCategory.BLUETOOTH,
    "SMARTCARDREADER": PeripheralCategory.SMART_CARD_READER,
    "SMARTCARD": PeripheralCategory.SMART_CARD,
    "SMARTCARDFILTER": PeripheralCategory.SMART_CARD,
    "BIOMETRIC": PeripheralCategory.BIOMETRIC,
    "WPD": PeripheralCategory.PORTABLE_DEVICE,
    "PORTS": PeripheralCategory.SERIAL_PORT,
    "PRINTER": PeripheralCategory.PRINTER_DEVICE,
    "MONITOR": PeripheralCategory.MONITOR,
    "SENSOR": PeripheralCategory.SENSOR,
    "MODEM": PeripheralCategory.MODEM,
    "USB": PeripheralCategory.USB_OTHER,
    "USBDEVICE": PeripheralCategory.USB_OTHER,
    "HIDCLASS": PeripheralCategory.HID_OTHER,
}

# Clases que solo interesan si el dispositivo está conectado por fuera (USB o Bluetooth).
EXTERNAL_ONLY = {
    PeripheralCategory.USB_OTHER,
    PeripheralCategory.HID_OTHER,
    PeripheralCategory.AUDIO,
}

# Concentradores, controladoras y piezas internas del bus USB: no son periféricos.
_INFRASTRUCTURE = re.compile(
    r"root hub|host controller|controladora|concentrador|usb hub|generic usb hub|composite device"
    r"|dispositivo compuesto|xhci|ehci|enumerator|enumerador",
    re.IGNORECASE,
)


def category_of(pnp_class: str | None, instance: str | None) -> PeripheralCategory | None:
    upper = (pnp_class or "").upper()
    if upper == "DISKDRIVE":
        return (
            PeripheralCategory.USB_STORAGE
            if (instance or "").upper().startswith("USBSTOR")
            else None
        )
    return _CATEGORIES.get(upper)


def is_bus_infrastructure(name: str | None) -> bool:
    return bool(name and _INFRASTRUCTURE.search(name))


# Puertos de colas virtuales: no hay hardware detrás.
_VIRTUAL_PORTS = re.compile(
    r"^(nul:|portprompt:|file:|xps|shrfax:|onenote|microsoft\.office\.onenote)", re.IGNORECASE
)
_VIRTUAL_DRIVERS = re.compile(r"pdf|xps|onenote|fax|send to", re.IGNORECASE)


def printer_connection(
    port_name: str | None, driver_name: str | None, *, is_network_queue: bool, has_tcp_port: bool
) -> PrinterConnection:
    port = (port_name or "").strip()
    lowered = port.lower()
    if port.startswith("\\\\") or (
        is_network_queue and not has_tcp_port and not lowered.startswith("wsd")
    ):
        return PrinterConnection.SHARED
    if _VIRTUAL_PORTS.match(port) or (
        driver_name and _VIRTUAL_DRIVERS.search(driver_name) and not has_tcp_port
    ):
        return PrinterConnection.VIRTUAL
    if has_tcp_port or _IP.search(port):
        return PrinterConnection.NETWORK_TCP
    if lowered.startswith("wsd"):
        return PrinterConnection.WSD
    if (
        lowered.startswith(("http://", "https://", "ipp"))
        or "universal print" in (driver_name or "").lower()
    ):
        return PrinterConnection.IPP
    if lowered.startswith(("usb", "dot4")):
        return PrinterConnection.USB
    return PrinterConnection.LOCAL_OTHER


def ip_in(text: str | None) -> str | None:
    match = _IP.search(text or "")
    if not match:
        return None
    if any(int(part) > 255 for part in match.group(1).split(".")):
        return None
    return match.group(1)


def driver_version_text(packed: int | None) -> str | None:
    """MSFT_PrinterDriver empaqueta la versión en 64 bits: 16 bits por componente."""
    if not packed or packed < 0:
        return None
    parts = [(packed >> shift) & 0xFFFF for shift in (48, 32, 16, 0)]
    return ".".join(str(part) for part in parts)


PRINTER_STATUS = {
    1: "other",
    2: "unknown",
    3: "idle",
    4: "printing",
    5: "warming_up",
    6: "stopped",
    7: "offline",
}
PRINTER_ERRORS = {
    3: "low_paper",
    4: "no_paper",
    5: "low_toner",
    6: "no_toner",
    7: "door_open",
    8: "jammed",
    9: "offline",
    10: "service_requested",
    11: "output_bin_full",
}


# --- Aparatos físicos a partir del árbol de dispositivos ----------------------------------------
# Windows parte un aparato en muchos nodos: un teclado con mouse y teclas multimedia son nueve
# («HID Keyboard Device» tres veces, «USB Input Device», «vendor-defined»…). El contenedor que
# Windows asigna a cada aparato los une; para lo integrado (todo en el contenedor del equipo) se
# une cada nodo con su padre. Así se lista lo que el técnico ve sobre la mesa.

# Clases de Windows que pueden ser un periférico (o parte de uno).
PERIPHERAL_CLASSES = (
    "Keyboard",
    "Mouse",
    "Camera",
    "Image",
    "MEDIA",
    "AudioEndpoint",
    "Bluetooth",
    "SmartCardReader",
    "SmartCard",
    "SmartCardFilter",
    "Biometric",
    "WPD",
    "Ports",
    "Printer",
    "Monitor",
    "Sensor",
    "Modem",
    "USB",
    "USBDevice",
    "HIDClass",
    "DiskDrive",
)

# Contenedor del propio equipo: todo lo integrado lo comparte, no sirve para agrupar.
COMPUTER_CONTAINER = "00000000-0000-0000-FFFF-FFFFFFFFFFFF"

# Un nodo así no es el aparato del que cuelgan sus hijos (concentradores, enumeradores del bus).
_NOT_A_PARENT = re.compile(
    r"root hub|host controller|usb hub|generic usb hub|enumerator|enumerador|controladora"
    r"|concentrador|xhci|ehci",
    re.IGNORECASE,
)

# Nombres que Windows pone a cualquier cosa: no identifican el aparato.
_GENERIC = re.compile(
    r"^(usb composite device|dispositivo compuesto usb|usb input device|dispositivo de entrada usb"
    r"|hid[- ]compliant.*|dispositivo .*compatible con hid.*|hid keyboard device"
    r"|i2c hid device|dispositivo hid i2c|usb device|dispositivo usb|usb receiver"
    r"|generic .*|standard .*|bluetooth peripheral device|bluetooth le device.*"
    r"|microsoft input configuration device|usb video device|usb mass storage device"
    r"|dispositivo de almacenamiento masivo usb)$",
    re.IGNORECASE,
)

_IN_PARENS = re.compile(r"\(([^()]{2,})\)\s*$")
_RECEIVER = re.compile(r"receiver|receptor|unifying|dongle|nano", re.IGNORECASE)
_BT_DEVICE = re.compile(r"^(BTHENUM|BTHLE)\\DEV_", re.IGNORECASE)

# Funciones que por sí solas no hacen de un nodo integrado un periférico (teclas del portátil).
_MINOR = {
    PeripheralFunction.MEDIA_KEYS,
    PeripheralFunction.SYSTEM_CONTROL,
    PeripheralFunction.LIGHTING,
    PeripheralFunction.FIRMWARE_UPDATE,
}

# Orden para elegir la función principal (la que define qué es el aparato).
_MAIN_ORDER = [
    PeripheralFunction.KEYBOARD,
    PeripheralFunction.TOUCHPAD,
    PeripheralFunction.MOUSE,
    PeripheralFunction.GAME_CONTROLLER,
    PeripheralFunction.CAMERA,
    PeripheralFunction.SCANNER,
    PeripheralFunction.HEADPHONES,
    PeripheralFunction.MICROPHONE,
    PeripheralFunction.SPEAKERS,
    PeripheralFunction.AUDIO,
    PeripheralFunction.FINGERPRINT,
    PeripheralFunction.DISPLAY,
    PeripheralFunction.STORAGE,
    PeripheralFunction.PRINTER,
    PeripheralFunction.PORTABLE,
    PeripheralFunction.BLUETOOTH_RADIO,
    PeripheralFunction.SMART_CARD,
    PeripheralFunction.SERIAL,
    PeripheralFunction.SENSOR,
    PeripheralFunction.MEDIA_KEYS,
    PeripheralFunction.SYSTEM_CONTROL,
    PeripheralFunction.LIGHTING,
    PeripheralFunction.FIRMWARE_UPDATE,
]

_CATEGORY_OF_FUNCTION = {
    PeripheralFunction.KEYBOARD: PeripheralCategory.KEYBOARD,
    PeripheralFunction.MOUSE: PeripheralCategory.MOUSE,
    PeripheralFunction.TOUCHPAD: PeripheralCategory.TOUCHPAD,
    PeripheralFunction.GAME_CONTROLLER: PeripheralCategory.GAME_CONTROLLER,
    PeripheralFunction.CAMERA: PeripheralCategory.CAMERA,
    PeripheralFunction.SCANNER: PeripheralCategory.IMAGING,
    PeripheralFunction.HEADPHONES: PeripheralCategory.AUDIO,
    PeripheralFunction.MICROPHONE: PeripheralCategory.AUDIO,
    PeripheralFunction.SPEAKERS: PeripheralCategory.AUDIO,
    PeripheralFunction.AUDIO: PeripheralCategory.AUDIO,
    PeripheralFunction.FINGERPRINT: PeripheralCategory.BIOMETRIC,
    PeripheralFunction.DISPLAY: PeripheralCategory.MONITOR,
    PeripheralFunction.STORAGE: PeripheralCategory.USB_STORAGE,
    PeripheralFunction.PRINTER: PeripheralCategory.PRINTER_DEVICE,
    PeripheralFunction.PORTABLE: PeripheralCategory.PORTABLE_DEVICE,
    PeripheralFunction.BLUETOOTH_RADIO: PeripheralCategory.BLUETOOTH,
    PeripheralFunction.SMART_CARD: PeripheralCategory.SMART_CARD_READER,
    PeripheralFunction.SERIAL: PeripheralCategory.SERIAL_PORT,
    PeripheralFunction.SENSOR: PeripheralCategory.SENSOR,
}

_SIMPLE_FUNCTIONS = {
    "BIOMETRIC": PeripheralFunction.FINGERPRINT,
    "MONITOR": PeripheralFunction.DISPLAY,
    "WPD": PeripheralFunction.PORTABLE,
    "PRINTER": PeripheralFunction.PRINTER,
    "PORTS": PeripheralFunction.SERIAL,
    "SENSOR": PeripheralFunction.SENSOR,
    "SMARTCARDREADER": PeripheralFunction.SMART_CARD,
}


def _audio_function(name: str) -> PeripheralFunction:
    if any(word in name for word in ("headphone", "auricular", "audífono", "headset")):
        return PeripheralFunction.HEADPHONES
    if any(word in name for word in ("microphone", "micrófono", "mic ")):
        return PeripheralFunction.MICROPHONE
    if any(word in name for word in ("speaker", "altavoz", "parlante")):
        return PeripheralFunction.SPEAKERS
    return PeripheralFunction.AUDIO


def function_of(node: DeviceNode) -> PeripheralFunction | None:  # noqa: PLR0911 - una regla por caso
    """Lo que hace un nodo, o None si es fontanería de Windows (interfaz USB, colección vendor)."""
    name = (node.name or "").lower()
    upper_class = (node.pnp_class or "").upper()
    instance = node.instance_id.upper()
    if "touch pad" in name or "touchpad" in name or "panel táctil" in name:
        return PeripheralFunction.TOUCHPAD
    if upper_class == "KEYBOARD":
        return PeripheralFunction.KEYBOARD
    if upper_class == "MOUSE":
        return PeripheralFunction.MOUSE
    if "LAMPARRAY" in instance or "lamparray" in name:
        return PeripheralFunction.LIGHTING
    if "consumer control" in name or "control de consumidor" in name:
        return PeripheralFunction.MEDIA_KEYS
    if "system controller" in name or "controlador de sistema" in name:
        return PeripheralFunction.SYSTEM_CONTROL
    if any(word in name for word in ("game controller", "gamepad", "xinput", "xbox")):
        return PeripheralFunction.GAME_CONTROLLER
    if "dfu" in name or "firmware" in name:
        return PeripheralFunction.FIRMWARE_UPDATE
    if upper_class == "CAMERA" or (upper_class == "IMAGE" and "camera" in name):
        return PeripheralFunction.CAMERA
    if upper_class == "IMAGE":
        return PeripheralFunction.SCANNER
    if upper_class == "AUDIOENDPOINT":
        return _audio_function(name)
    if upper_class == "MEDIA":
        return PeripheralFunction.AUDIO
    if upper_class == "BLUETOOTH":
        is_radio = instance.startswith(("USB\\", "PCI\\")) or "radio" in name or "adapter" in name
        return PeripheralFunction.BLUETOOTH_RADIO if is_radio else None
    if upper_class in _SIMPLE_FUNCTIONS:
        return _SIMPLE_FUNCTIONS[upper_class]
    if upper_class == "DISKDRIVE" and instance.startswith("USBSTOR"):
        return PeripheralFunction.STORAGE
    return None


@dataclass(frozen=True)
class DeviceGroup:
    """Un aparato físico: sus nodos y lo que se deduce de ellos."""

    root: DeviceNode
    members: tuple[DeviceNode, ...]
    present: bool
    name: str | None
    generic_name: bool
    functions: tuple[PeripheralFunction, ...]
    category: PeripheralCategory
    connection: PeripheralConnection
    container_id: str | None
    is_bluetooth_device: bool
    last_arrival: datetime | None
    last_removal: datetime | None

    @property
    def hardware(self) -> HardwareId:
        for node in (self.root, *self.members):
            parsed = parse_instance_id(node.instance_id)
            if parsed.vendor_id:
                return parsed
        return parse_instance_id(self.root.instance_id)

    @property
    def driver_infs(self) -> list[str]:
        """Controladores de terceros: los de Windows (`input.inf`) siempre están."""
        found = {
            node.driver_inf.lower()
            for node in self.members
            if node.driver_inf and node.driver_inf.lower().startswith("oem")
        }
        return sorted(found)

    @property
    def main_member(self) -> DeviceNode:
        for function in _MAIN_ORDER:
            for node in self.members:
                if function_of(node) is function:
                    return node
        return self.root


def _union_find(nodes: list[DeviceNode]) -> list[list[DeviceNode]]:
    by_id = {node.instance_id.upper(): node for node in nodes}
    parent: dict[str, str] = {key: key for key in by_id}

    def find(key: str) -> str:
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(a: str, b: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a

    first_in_container: dict[str, str] = {}
    for key, node in by_id.items():
        container = (node.container_id or "").upper()
        if container and container != COMPUTER_CONTAINER:
            union(first_in_container.setdefault(container, key), key)
    for key, node in by_id.items():
        above = by_id.get((node.parent or "").upper())
        if above is not None and not _NOT_A_PARENT.search(above.name or ""):
            union(above.instance_id.upper(), key)

    groups: dict[str, list[DeviceNode]] = {}
    for key, node in by_id.items():
        groups.setdefault(find(key), []).append(node)
    return list(groups.values())


def _best_name(root: DeviceNode, members: list[DeviceNode], bt: DeviceNode | None) -> str | None:
    if bt and bt.name:
        return bt.name
    candidates = [root.name, root.bus_description]
    candidates += [node.bus_description for node in members]
    candidates += [node.name for node in members if function_of(node) is not None]
    for candidate in candidates:
        if not candidate:
            continue
        # «Generic Monitor (LG ULTRAGEAR)»: el modelo real va entre paréntesis.
        inner = _IN_PARENS.search(candidate)
        if _GENERIC.match(candidate.strip()) and inner:
            return inner.group(1).strip()
        if not _GENERIC.match(candidate.strip()):
            return candidate.strip()
    return None


def _connection(
    root: DeviceNode, members: list[DeviceNode], functions: list[PeripheralFunction], bt: bool
) -> PeripheralConnection:
    if bt:
        return PeripheralConnection.BLUETOOTH
    if PeripheralFunction.DISPLAY in functions:
        container = (root.container_id or "").upper()
        external = bool(container) and container != COMPUTER_CONTAINER
        return PeripheralConnection.VIDEO if external else PeripheralConnection.INTERNAL
    found = [parse_instance_id(node.instance_id).connection for node in [root, *members]]
    for kind in (PeripheralConnection.USB, PeripheralConnection.INTERNAL):
        if kind in found:
            return kind
    return found[0]


def _category(
    ordered: list[PeripheralFunction],
    root: DeviceNode,
    visible: list[DeviceNode],
    external: bool,
    bt: bool,
) -> PeripheralCategory:
    receiver = any(
        _RECEIVER.search(text or "")
        for node in visible
        for text in (node.name, node.bus_description)
    )
    if receiver and external and not bt:
        return PeripheralCategory.WIRELESS_RECEIVER
    if ordered:
        return _CATEGORY_OF_FUNCTION.get(ordered[0], PeripheralCategory.HID_OTHER)
    if bt:
        return PeripheralCategory.BLUETOOTH
    return category_of(root.pnp_class, root.instance_id) or PeripheralCategory.USB_OTHER


def _describe(members: list[DeviceNode]) -> DeviceGroup | None:
    ids = {node.instance_id.upper() for node in members}
    roots = [node for node in members if (node.parent or "").upper() not in ids]
    bt_node = next((node for node in members if _BT_DEVICE.match(node.instance_id)), None)
    root = bt_node or (roots[0] if roots else members[0])
    present = any(node.present for node in members)
    visible = [node for node in members if node.present] if present else members
    found = {function_of(node) for node in visible}
    if PeripheralFunction.TOUCHPAD in found:
        found.discard(PeripheralFunction.MOUSE)  # el touchpad se declara también como mouse
    ordered = [function for function in _MAIN_ORDER if function in found]
    name = _best_name(root, visible, bt_node)
    connection = _connection(root, visible, ordered, bt_node is not None)
    external = connection in (PeripheralConnection.USB, PeripheralConnection.BLUETOOTH)
    meaningful = [function for function in ordered if function not in _MINOR]
    if not meaningful and bt_node is None and not (external and (ordered or name)):
        return None  # concentradores, enumeradores, teclas del portátil sueltas
    if not ordered and is_bus_infrastructure(root.name):
        return None
    if set(ordered) <= {PeripheralFunction.AUDIO} and not external:
        return None  # un controlador de audio sin entrada ni salida no es un aparato
    arrivals = [node.last_arrival for node in members if node.last_arrival]
    removals = [node.last_removal for node in members if node.last_removal]
    container = (root.container_id or "").upper() or None
    return DeviceGroup(
        root=root,
        members=tuple(sorted(visible, key=lambda node: node.instance_id)),
        present=present,
        name=name or root.name,
        generic_name=name is None,
        functions=tuple(ordered),
        category=_category(ordered, root, visible, external, bt_node is not None),
        connection=connection,
        container_id=container if container != COMPUTER_CONTAINER else None,
        is_bluetooth_device=bt_node is not None,
        last_arrival=max(arrivals) if arrivals else None,
        last_removal=max(removals) if removals else None,
    )


def group_devices(nodes: list[DeviceNode]) -> list[DeviceGroup]:
    """Une los nodos de cada aparato y lo describe. Se descartan los grupos que solo son piezas
    del bus (concentradores, enumeradores) o funciones menores de lo integrado."""
    relevant = [node for node in nodes if category_of(node.pnp_class, node.instance_id)]
    described = (_describe(members) for members in _union_find(relevant))
    return [group for group in described if group is not None]


def same_device(group: DeviceGroup) -> tuple[str, str, bool]:
    """Clave para mostrar como uno lo que Windows recuerda varias veces (un control con dos
    direcciones Bluetooth, un teléfono con varias interfaces)."""
    return ((group.name or "").strip().lower(), group.connection.value, group.is_bluetooth_device)

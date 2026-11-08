"""Árbol de dispositivos de Windows por cfgmgr32: presentes y no presentes, con su contenedor.

Win32_PnPEntity solo lista lo conectado y no dice qué funciones son del mismo aparato. El
administrador de configuración sí: cada nodo trae su contenedor (el aparato físico), su padre, si
está presente y cuándo se conectó o se quitó por última vez. Leer no cambia nada; quitar un nodo
no presente (`uninstall`) es la única escritura y solo la usa la herramienta de soporte.
"""

from __future__ import annotations

import ctypes
import uuid
from collections.abc import Iterable
from ctypes import wintypes
from datetime import UTC, datetime, timedelta

from honey_check.domain.peripherals import DeviceNode

_cfgmgr = ctypes.WinDLL("cfgmgr32", use_last_error=True)

_CR_SUCCESS = 0
_CR_BUFFER_SMALL = 0x1A
_CM_LOCATE_DEVNODE_PHANTOM = 0x1

_TYPE_STRING = 0x12
_TYPE_GUID = 0x0D
_TYPE_FILETIME = 0x10
_TYPE_BOOLEAN = 0x11
_TYPE_UINT32 = 0x07
_TYPE_STRING_LIST = 0x2012


class _DevPropKey(ctypes.Structure):
    _fields_ = (("fmtid", ctypes.c_byte * 16), ("pid", wintypes.ULONG))


def _key(fmtid: str, pid: int) -> _DevPropKey:
    key = _DevPropKey()
    ctypes.memmove(key.fmtid, uuid.UUID(fmtid).bytes_le, 16)
    key.pid = pid
    return key


_DEVICE = "a45c254e-df1c-4efd-8020-67d146a850e0"
_DEVICE_2 = "540b947e-8b40-45bc-a8a2-6a0b894cbda2"
_DEVICE_3 = "4340a6c5-93fa-4706-972c-7b648008a5a7"
_DRIVER = "a8b865dd-2e3d-4094-ad97-e593a70c75d6"
_DATES = "83da6326-97a6-4088-9453-a1923f573b29"

_DESC = _key(_DEVICE, 2)
_CLASS = _key(_DEVICE, 9)
_HARDWARE_IDS = _key(_DEVICE, 3)
_COMPATIBLE_IDS = _key(_DEVICE, 4)
_MANUFACTURER = _key(_DEVICE, 13)
_FRIENDLY = _key(_DEVICE, 14)
_BUS_DESC = _key(_DEVICE_2, 4)
_PRESENT = _key(_DEVICE_2, 5)
_CONTAINER = _key("8c7ed206-3f8a-4827-b3ab-ae9e1faefc6c", 2)
_PARENT = _key(_DEVICE_3, 8)
_PROBLEM = _key(_DEVICE_3, 3)
_INF = _key(_DRIVER, 5)
_ARRIVAL = _key(_DATES, 102)
_REMOVAL = _key(_DATES, 103)

_cfgmgr.CM_Get_Device_ID_List_SizeW.argtypes = (
    ctypes.POINTER(wintypes.ULONG),
    wintypes.LPCWSTR,
    wintypes.ULONG,
)
_cfgmgr.CM_Get_Device_ID_ListW.argtypes = (
    wintypes.LPCWSTR,
    wintypes.LPWSTR,
    wintypes.ULONG,
    wintypes.ULONG,
)
_cfgmgr.CM_Locate_DevNodeW.argtypes = (
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPCWSTR,
    wintypes.ULONG,
)
_cfgmgr.CM_Get_DevNode_PropertyW.argtypes = (
    wintypes.DWORD,
    ctypes.POINTER(_DevPropKey),
    ctypes.POINTER(wintypes.ULONG),
    ctypes.c_void_p,
    ctypes.POINTER(wintypes.ULONG),
    wintypes.ULONG,
)
_cfgmgr.CM_Uninstall_DevNode.argtypes = (wintypes.DWORD, wintypes.ULONG)

_FILETIME_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)


def _all_ids() -> list[str]:
    for _ in range(3):  # la lista puede crecer entre las dos llamadas
        size = wintypes.ULONG(0)
        if _cfgmgr.CM_Get_Device_ID_List_SizeW(ctypes.byref(size), None, 0) != _CR_SUCCESS:
            return []
        buffer = ctypes.create_unicode_buffer(size.value)
        result = _cfgmgr.CM_Get_Device_ID_ListW(None, buffer, size.value, 0)
        if result == _CR_SUCCESS:
            listing = ctypes.wstring_at(buffer, size.value)
            return [item for item in listing.split("\0") if item]
        if result != _CR_BUFFER_SMALL:
            return []
    return []


def _locate(instance_id: str) -> int | None:
    devinst = wintypes.DWORD(0)
    if (
        _cfgmgr.CM_Locate_DevNodeW(ctypes.byref(devinst), instance_id, _CM_LOCATE_DEVNODE_PHANTOM)
        != _CR_SUCCESS
    ):
        return None
    return int(devinst.value)


def _property(devinst: int, key: _DevPropKey) -> object:
    kind = wintypes.ULONG(0)
    size = wintypes.ULONG(0)
    result = _cfgmgr.CM_Get_DevNode_PropertyW(
        devinst, ctypes.byref(key), ctypes.byref(kind), None, ctypes.byref(size), 0
    )
    if result != _CR_BUFFER_SMALL or not size.value:
        return None
    buffer = ctypes.create_string_buffer(size.value)
    if (
        _cfgmgr.CM_Get_DevNode_PropertyW(
            devinst, ctypes.byref(key), ctypes.byref(kind), buffer, ctypes.byref(size), 0
        )
        != _CR_SUCCESS
    ):
        return None
    raw = buffer.raw[: size.value]
    if kind.value == _TYPE_STRING:
        return raw.decode("utf-16-le").rstrip("\0") or None
    if kind.value == _TYPE_STRING_LIST:
        return tuple(item for item in raw.decode("utf-16-le").split("\0") if item)
    if kind.value == _TYPE_GUID and len(raw) == 16:
        return str(uuid.UUID(bytes_le=raw)).upper()
    if kind.value == _TYPE_BOOLEAN:
        return raw[:1] != b"\0"
    if kind.value == _TYPE_UINT32 and len(raw) == 4:
        return int.from_bytes(raw, "little")
    if kind.value == _TYPE_FILETIME and len(raw) == 8:
        ticks = int.from_bytes(raw, "little")
        return _FILETIME_EPOCH + timedelta(microseconds=ticks // 10) if ticks else None
    return None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _date(value: object) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _list(value: object) -> tuple[str, ...]:
    return value if isinstance(value, tuple) else ()


def read_node(instance_id: str) -> DeviceNode | None:
    devinst = _locate(instance_id)
    if devinst is None:
        return None
    present = _property(devinst, _PRESENT)
    problem = _property(devinst, _PROBLEM)
    return DeviceNode(
        instance_id=instance_id,
        name=_text(_property(devinst, _FRIENDLY)) or _text(_property(devinst, _DESC)),
        pnp_class=_text(_property(devinst, _CLASS)),
        manufacturer=_text(_property(devinst, _MANUFACTURER)),
        container_id=_text(_property(devinst, _CONTAINER)),
        parent=_text(_property(devinst, _PARENT)),
        bus_description=_text(_property(devinst, _BUS_DESC)),
        present=bool(present) if isinstance(present, bool) else True,
        problem_code=problem if isinstance(problem, int) else 0,
        driver_inf=_text(_property(devinst, _INF)),
        last_arrival=_date(_property(devinst, _ARRIVAL)),
        last_removal=_date(_property(devinst, _REMOVAL)),
        hardware_ids=_list(_property(devinst, _HARDWARE_IDS)),
        compatible_ids=_list(_property(devinst, _COMPATIBLE_IDS)),
    )


class WinDeviceTree:
    """Nodos de las clases pedidas, presentes o no. Solo lectura."""

    def nodes(self, classes: Iterable[str] | None) -> list[DeviceNode]:
        """Los de esas clases; con None, todos (también los sin clase: aparatos sin controlador)."""
        wanted = None if classes is None else {name.upper() for name in classes}
        found: list[DeviceNode] = []
        for instance_id in _all_ids():
            devinst = _locate(instance_id)
            if devinst is None:
                continue
            pnp_class = _text(_property(devinst, _CLASS))
            if wanted is not None and (not pnp_class or pnp_class.upper() not in wanted):
                continue
            node = read_node(instance_id)
            if node is not None:
                found.append(node)
        return found


def is_present(instance_id: str) -> bool | None:
    """Verdadero si está conectado; None si Windows ya no lo conoce (fue quitado)."""
    devinst = _locate(instance_id)
    if devinst is None:
        return None
    present = _property(devinst, _PRESENT)
    return bool(present) if isinstance(present, bool) else True


def uninstall(instance_id: str) -> int:
    """Quita un nodo de dispositivo (requiere administrador). 0 si se quitó; otro valor es el
    código CR_ de cfgmgr32."""
    devinst = _locate(instance_id)
    if devinst is None:
        return 0
    return int(_cfgmgr.CM_Uninstall_DevNode(devinst, 0))

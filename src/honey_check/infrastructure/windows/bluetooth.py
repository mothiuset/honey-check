"""Olvidar un aparato Bluetooth emparejado (BluetoothRemoveDevice de bthprops.cpl).

Es lo mismo que «Quitar dispositivo» en Configuración: Windows borra el emparejamiento y sus
nodos. Para volver a usarlo hay que emparejarlo de nuevo; no hay respaldo posible de un
emparejamiento.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes


class _Address(ctypes.Structure):
    _fields_ = (("value", ctypes.c_ulonglong),)


_ERROR_NOT_FOUND = 1168


def forget(mac: str) -> int:
    """0 si Windows olvidó el aparato (o ya no lo recordaba); otro valor es el código Win32."""
    bthprops = ctypes.WinDLL("bthprops.cpl", use_last_error=True)
    bthprops.BluetoothRemoveDevice.argtypes = (ctypes.POINTER(_Address),)
    bthprops.BluetoothRemoveDevice.restype = wintypes.DWORD
    address = _Address(int(mac.replace(":", ""), 16))
    result = int(bthprops.BluetoothRemoveDevice(ctypes.byref(address)))
    return 0 if result == _ERROR_NOT_FOUND else result

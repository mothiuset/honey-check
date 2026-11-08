"""Lo mínimo de COM con ctypes: inicialización por hilo, llamadas por vtable, BSTR y VARIANT.

Sin dependencias externas: Windows trae todo lo necesario (ole32 y oleaut32).
"""

from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from ctypes import wintypes
from typing import Any

_ole32 = ctypes.WinDLL("ole32", use_last_error=True)
_oleaut32 = ctypes.WinDLL("oleaut32", use_last_error=True)

COINIT_MULTITHREADED = 0x0
S_OK = 0
S_FALSE = 1
RPC_E_CHANGED_MODE = 0x80010106
RPC_E_TOO_LATE = 0x80010119
CLSCTX_INPROC_SERVER = 0x1

VT_EMPTY, VT_NULL, VT_I2, VT_I4, VT_R4, VT_R8 = 0, 1, 2, 3, 4, 5
VT_BSTR, VT_DISPATCH, VT_BOOL, VT_UNKNOWN = 8, 9, 11, 13
VT_I1, VT_UI1, VT_UI2, VT_UI4, VT_I8, VT_UI8, VT_INT, VT_UINT = 16, 17, 18, 19, 20, 21, 22, 23
VT_ARRAY = 0x2000
VT_BYREF = 0x4000


class GUID(ctypes.Structure):
    _fields_ = (
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    )

    @classmethod
    def parse(cls, text: str) -> GUID:
        guid = cls()
        if _ole32.CLSIDFromString(text, ctypes.byref(guid)) != S_OK:
            raise ValueError(text)
        return guid


class VARIANT(ctypes.Structure):
    # 24 bytes en 64 bits: vt, tres reservados y una unión de 16 bytes.
    _fields_ = (
        ("vt", ctypes.c_ushort),
        ("reserved1", ctypes.c_ushort),
        ("reserved2", ctypes.c_ushort),
        ("reserved3", ctypes.c_ushort),
        ("data", ctypes.c_ubyte * 16),
    )


_ole32.CoInitializeEx.argtypes = (ctypes.c_void_p, wintypes.DWORD)
_ole32.CoInitializeEx.restype = ctypes.c_long
_ole32.CoUninitialize.argtypes = ()
_ole32.CoInitializeSecurity.argtypes = (
    ctypes.c_void_p,
    ctypes.c_long,
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.c_void_p,
)
_ole32.CoInitializeSecurity.restype = ctypes.c_long
_ole32.CoCreateInstance.argtypes = (
    ctypes.POINTER(GUID),
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(GUID),
    ctypes.POINTER(ctypes.c_void_p),
)
_ole32.CoCreateInstance.restype = ctypes.c_long
_ole32.CoSetProxyBlanket.argtypes = (
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
)
_ole32.CoSetProxyBlanket.restype = ctypes.c_long
_ole32.CLSIDFromString.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(GUID))
_ole32.CLSIDFromString.restype = ctypes.c_long
_oleaut32.SysAllocString.argtypes = (wintypes.LPCWSTR,)
_oleaut32.SysAllocString.restype = ctypes.c_void_p
_oleaut32.SysFreeString.argtypes = (ctypes.c_void_p,)
_oleaut32.SysStringLen.argtypes = (ctypes.c_void_p,)
_oleaut32.SysStringLen.restype = ctypes.c_uint
_oleaut32.VariantInit.argtypes = (ctypes.POINTER(VARIANT),)
_oleaut32.VariantClear.argtypes = (ctypes.POINTER(VARIANT),)
_oleaut32.VariantClear.restype = ctypes.c_long
_oleaut32.SafeArrayGetLBound.argtypes = (
    ctypes.c_void_p,
    ctypes.c_uint,
    ctypes.POINTER(ctypes.c_long),
)
_oleaut32.SafeArrayGetLBound.restype = ctypes.c_long
_oleaut32.SafeArrayGetUBound.argtypes = (
    ctypes.c_void_p,
    ctypes.c_uint,
    ctypes.POINTER(ctypes.c_long),
)
_oleaut32.SafeArrayGetUBound.restype = ctypes.c_long
_oleaut32.SafeArrayAccessData.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
_oleaut32.SafeArrayAccessData.restype = ctypes.c_long
_oleaut32.SafeArrayUnaccessData.argtypes = (ctypes.c_void_p,)
_oleaut32.SafeArrayUnaccessData.restype = ctypes.c_long
_oleaut32.SafeArrayGetElemsize.argtypes = (ctypes.c_void_p,)
_oleaut32.SafeArrayGetElemsize.restype = ctypes.c_uint


class ComError(Exception):
    def __init__(self, hresult: int, where: str) -> None:
        self.hresult = hresult & 0xFFFFFFFF
        super().__init__(f"{where}: 0x{self.hresult:08X}")


def check(hresult: int, where: str) -> int:
    if hresult < 0:
        raise ComError(hresult, where)
    return hresult


_security_lock = threading.Lock()
_security_done = False


def _initialize_security() -> None:
    """Una vez por proceso: identidad del llamante para WMI. Si ya está fijada, se respeta."""
    global _security_done
    with _security_lock:
        if _security_done:
            return
        hr = _ole32.CoInitializeSecurity(None, -1, None, None, 0, 3, None, 0, None)
        if hr < 0 and (hr & 0xFFFFFFFF) != RPC_E_TOO_LATE:
            raise ComError(hr, "CoInitializeSecurity")
        _security_done = True


@contextmanager
def com_apartment() -> Iterator[None]:
    """COM inicializado en este hilo durante el bloque (multihilo), y liberado al salir."""
    hr = _ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
    owned = hr in (S_OK, S_FALSE)
    if hr < 0 and (hr & 0xFFFFFFFF) != RPC_E_CHANGED_MODE:
        raise ComError(hr, "CoInitializeEx")
    try:
        _initialize_security()
        yield
    finally:
        if owned:
            _ole32.CoUninitialize()


def create_instance(clsid: GUID, iid: GUID) -> ctypes.c_void_p:
    pointer = ctypes.c_void_p()
    check(
        _ole32.CoCreateInstance(
            ctypes.byref(clsid),
            None,
            CLSCTX_INPROC_SERVER,
            ctypes.byref(iid),
            ctypes.byref(pointer),
        ),
        "CoCreateInstance",
    )
    return pointer


def set_proxy_blanket(proxy: ctypes.c_void_p) -> None:
    # RPC_C_AUTHN_WINNT, sin autorización, nivel de llamada, suplantación.
    check(_ole32.CoSetProxyBlanket(proxy, 10, 0, None, 3, 3, None, 0), "CoSetProxyBlanket")


def method(pointer: ctypes.c_void_p, index: int, *argtypes: Any) -> Callable[..., int]:
    """Método `index` de la vtable de la interfaz; devuelve el HRESULT."""
    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    prototype = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
    function = prototype(vtable[index])
    return lambda *args: function(pointer, *args)


def release(pointer: ctypes.c_void_p | None) -> None:
    if pointer:
        method(pointer, 2)()


class Bstr:
    """BSTR propio, liberado al salir del bloque."""

    def __init__(self, text: str | None) -> None:
        self.value = _oleaut32.SysAllocString(text) if text is not None else None

    def __enter__(self) -> ctypes.c_void_p | None:
        return self.value

    def __exit__(self, *_: object) -> None:
        if self.value:
            _oleaut32.SysFreeString(self.value)


def new_variant() -> VARIANT:
    variant = VARIANT()
    _oleaut32.VariantInit(ctypes.byref(variant))
    return variant


def clear_variant(variant: VARIANT) -> None:
    _oleaut32.VariantClear(ctypes.byref(variant))


def _bstr_text(pointer: int | None) -> str | None:
    if not pointer:
        return None
    return ctypes.wstring_at(pointer, _oleaut32.SysStringLen(pointer))


_SCALARS: dict[int, Any] = {
    VT_I1: ctypes.c_byte,
    VT_UI1: ctypes.c_ubyte,
    VT_I2: ctypes.c_short,
    VT_UI2: ctypes.c_ushort,
    VT_I4: ctypes.c_long,
    VT_UI4: ctypes.c_ulong,
    VT_INT: ctypes.c_int,
    VT_UINT: ctypes.c_uint,
    VT_I8: ctypes.c_longlong,
    VT_UI8: ctypes.c_ulonglong,
    VT_R4: ctypes.c_float,
    VT_R8: ctypes.c_double,
}


def _scalar_at(address: int, vt: int) -> Any:
    if vt == VT_BSTR:
        return _bstr_text(ctypes.c_void_p.from_address(address).value)
    if vt == VT_BOOL:
        return ctypes.c_short.from_address(address).value != 0
    kind = _SCALARS.get(vt)
    if kind is None:
        return None  # objetos incrustados y tipos que el inventario no usa
    return kind.from_address(address).value


def _array_values(parray: int, vt: int) -> list[Any]:
    lower, upper = ctypes.c_long(), ctypes.c_long()
    check(_oleaut32.SafeArrayGetLBound(parray, 1, ctypes.byref(lower)), "SafeArrayGetLBound")
    check(_oleaut32.SafeArrayGetUBound(parray, 1, ctypes.byref(upper)), "SafeArrayGetUBound")
    size = _oleaut32.SafeArrayGetElemsize(parray)
    data = ctypes.c_void_p()
    check(_oleaut32.SafeArrayAccessData(parray, ctypes.byref(data)), "SafeArrayAccessData")
    try:
        base = data.value or 0
        return [_scalar_at(base + i * size, vt) for i in range(upper.value - lower.value + 1)]
    finally:
        _oleaut32.SafeArrayUnaccessData(parray)


def variant_value(variant: VARIANT) -> Any:
    vt = variant.vt
    if vt in (VT_EMPTY, VT_NULL):
        return None
    address = ctypes.addressof(variant) + VARIANT.data.offset
    if vt & VT_ARRAY:
        parray = ctypes.c_void_p.from_address(address).value
        return _array_values(parray, vt & 0x0FFF) if parray else []
    if vt & VT_BYREF:
        return None
    return _scalar_at(address, vt)


_oleaut32.SysAllocString.restype = ctypes.c_void_p


def variant_from(value: object) -> VARIANT:
    """VARIANT de entrada para un método WMI: texto, entero o booleano."""
    variant = new_variant()
    address = ctypes.addressof(variant) + VARIANT.data.offset
    if isinstance(value, bool):
        variant.vt = VT_BOOL
        ctypes.c_short.from_address(address).value = -1 if value else 0
    elif isinstance(value, int):
        variant.vt = VT_I4
        ctypes.c_long.from_address(address).value = value
    elif isinstance(value, str):
        variant.vt = VT_BSTR
        ctypes.c_void_p.from_address(address).value = _oleaut32.SysAllocString(value)
    else:
        raise TypeError(type(value).__name__)
    return variant

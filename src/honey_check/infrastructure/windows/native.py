"""Consultas nativas de Windows que no requieren WMI ni permisos elevados."""

from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes

from honey_check.application.ports import NativeDisplayMode, TpmNativeInfo

log = logging.getLogger(__name__)

_FIRMWARE_TYPES = {1: "legacy_bios", 2: "uefi"}
_MACHINES = {0x014C: "x86", 0x8664: "x64", 0xAA64: "arm64", 0x01C4: "arm"}
_TPM_VERSIONS = {1: "1.2", 2: "2.0"}
_TBS_SUCCESS = 0
_TBS_NO_TPM = (0x8028400F,)  # TBS_E_TPM_NOT_FOUND


class _TbsDeviceInfo(ctypes.Structure):
    _fields_ = (
        ("structVersion", wintypes.UINT),
        ("tpmVersion", wintypes.UINT),
        ("tpmInterfaceType", wintypes.UINT),
        ("tpmImpRevision", wintypes.UINT),
    )


class _DisplayDevice(ctypes.Structure):
    _fields_ = (
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    )


class _DevMode(ctypes.Structure):
    _fields_ = (
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPositionX", wintypes.LONG),
        ("dmPositionY", wintypes.LONG),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
    )


_DISPLAY_ACTIVE = 0x1
_DISPLAY_PRIMARY = 0x4
_ENUM_CURRENT_SETTINGS = -1 & 0xFFFFFFFF


class WinNativeSystem:
    def computer_name(self) -> str | None:
        size = wintypes.DWORD(256)
        buffer = ctypes.create_unicode_buffer(size.value)
        # ComputerNameDnsHostname: el nombre visible, sin el límite de 15 caracteres de NetBIOS.
        if ctypes.windll.kernel32.GetComputerNameExW(1, buffer, ctypes.byref(size)):
            return buffer.value or None
        return None

    def firmware_mode(self) -> str | None:
        kind = wintypes.DWORD()
        try:
            function = ctypes.windll.kernel32.GetFirmwareType
        except AttributeError:
            return None
        if not function(ctypes.byref(kind)):
            return None
        return _FIRMWARE_TYPES.get(kind.value)

    def native_architecture(self) -> str | None:
        """Arquitectura real del equipo, también bajo emulación x64 en ARM64."""
        process_machine = wintypes.USHORT()
        native_machine = wintypes.USHORT()
        kernel32 = ctypes.windll.kernel32
        try:
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            ok = kernel32.IsWow64Process2(
                wintypes.HANDLE(kernel32.GetCurrentProcess()),
                ctypes.byref(process_machine),
                ctypes.byref(native_machine),
            )
        except AttributeError:
            return None
        return _MACHINES.get(native_machine.value) if ok else None

    def is_elevated(self) -> bool | None:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return None

    def tpm_info(self) -> TpmNativeInfo | None:
        """Tbsi_GetDeviceInfo funciona sin elevación, a diferencia de Win32_Tpm."""
        try:
            tbs = ctypes.WinDLL("tbs")
        except OSError:
            return None
        info = _TbsDeviceInfo()
        tbs.Tbsi_GetDeviceInfo.argtypes = (wintypes.UINT, wintypes.LPVOID)
        tbs.Tbsi_GetDeviceInfo.restype = wintypes.UINT
        result = tbs.Tbsi_GetDeviceInfo(ctypes.sizeof(info), ctypes.byref(info))
        if result == _TBS_SUCCESS:
            return TpmNativeInfo(True, _TPM_VERSIONS.get(info.tpmVersion))
        if result in _TBS_NO_TPM:
            return TpmNativeInfo(False, None)
        log.info("Tbsi_GetDeviceInfo devolvió 0x%08X", result)
        return None

    def display_modes(self) -> list[NativeDisplayMode]:
        user32 = ctypes.windll.user32
        modes: list[NativeDisplayMode] = []
        index = 0
        while index < 32:
            device = _DisplayDevice()
            device.cb = ctypes.sizeof(device)
            if not user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
                break
            index += 1
            if not device.StateFlags & _DISPLAY_ACTIVE:
                continue
            mode = _DevMode()
            mode.dmSize = ctypes.sizeof(mode)
            if user32.EnumDisplaySettingsW(
                device.DeviceName, _ENUM_CURRENT_SETTINGS, ctypes.byref(mode)
            ):
                modes.append(
                    NativeDisplayMode(
                        device=device.DeviceString or device.DeviceName,
                        is_primary=bool(device.StateFlags & _DISPLAY_PRIMARY),
                        width=mode.dmPelsWidth,
                        height=mode.dmPelsHeight,
                        refresh_hz=mode.dmDisplayFrequency if mode.dmDisplayFrequency > 1 else None,
                    )
                )
        return modes

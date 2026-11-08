"""Adaptador de solo lectura del Registro: las claves siempre se abren con KEY_READ."""

from __future__ import annotations

import winreg
from datetime import UTC, datetime, timedelta
from typing import Any

from honey_check.application.ports import (
    RegistryAccessDenied,
    RegistryHive,
    RegistryKeyMissing,
    RegistryView,
)

_HIVES = {
    RegistryHive.LOCAL_MACHINE: winreg.HKEY_LOCAL_MACHINE,
    RegistryHive.CURRENT_USER: winreg.HKEY_CURRENT_USER,
}
_VIEW_FLAGS = {
    RegistryView.DEFAULT: 0,
    RegistryView.BITS_64: winreg.KEY_WOW64_64KEY,
    RegistryView.BITS_32: winreg.KEY_WOW64_32KEY,
}
_WINDOWS_EPOCH = datetime(1601, 1, 1, tzinfo=UTC)
_MAX_VALUE_LENGTH = 8192


def _open(hive: RegistryHive, path: str, view: RegistryView) -> winreg.HKEYType:
    try:
        return winreg.OpenKeyEx(_HIVES[hive], path, 0, winreg.KEY_READ | _VIEW_FLAGS[view])
    except FileNotFoundError as error:
        raise RegistryKeyMissing(path) from error
    except PermissionError as error:
        raise RegistryAccessDenied(path) from error


class WinRegistry:
    def subkeys(self, hive: RegistryHive, path: str, view: RegistryView) -> list[str]:
        with _open(hive, path, view) as key:
            count = winreg.QueryInfoKey(key)[0]
            names: list[str] = []
            for index in range(count):
                try:
                    names.append(winreg.EnumKey(key, index))
                except OSError:
                    break  # La clave cambió mientras se leía.
            return names

    def values(self, hive: RegistryHive, path: str, view: RegistryView) -> dict[str, Any]:
        with _open(hive, path, view) as key:
            count = winreg.QueryInfoKey(key)[1]
            found: dict[str, Any] = {}
            for index in range(count):
                try:
                    name, value, kind = winreg.EnumValue(key, index)
                except OSError:
                    break
                if kind == winreg.REG_EXPAND_SZ and isinstance(value, str):
                    value = winreg.ExpandEnvironmentStrings(value)
                if isinstance(value, str):
                    value = value[:_MAX_VALUE_LENGTH]
                elif isinstance(value, bytes):
                    continue  # Ningún módulo usa valores binarios; evita conservarlos sin motivo.
                found[name] = value
            return found

    def last_write(self, hive: RegistryHive, path: str, view: RegistryView) -> datetime | None:
        with _open(hive, path, view) as key:
            ticks = winreg.QueryInfoKey(key)[2]
        return _WINDOWS_EPOCH + timedelta(microseconds=ticks / 10) if ticks else None

"""Desinstalar y eliminar restos: partes puras (sin tocar el equipo)."""

from __future__ import annotations

import pytest

from honey_check.application.support.ports import UserSession
from honey_check.infrastructure.support.tools.programs import (
    Leftover,
    base_name,
    count_phrase,
    packed_guid,
)
from honey_check.infrastructure.windows.errors import (
    Failure,
    installer_exit,
    shell_file_operation,
    win32,
)
from honey_check.infrastructure.windows.session import user_registry_key


def test_packed_guid_matches_windows_installer() -> None:
    # Ejemplo documentado de la forma comprimida de un código de producto.
    assert packed_guid("{90120000-0030-0000-0000-0000000FF1CE}") == (
        "00002109030000000000000000F01FEC"
    )


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Programa Ficticio 2.3 (x64)", "Programa Ficticio"),
        ("Editor Demo v10", "Editor Demo"),
        ("Visor", "Visor"),
    ],
)
def test_base_name_drops_version_and_architecture(name: str, expected: str) -> None:
    assert base_name(name) == expected


def test_shell_codes_are_not_read_as_win32() -> None:
    # 0x78 en SHFileOperation es «acceso denegado»; como Win32 sería otra cosa.
    denied = shell_file_operation(0x78)
    assert denied.failure is Failure.NEEDS_ADMIN
    assert "administrador" in denied.message
    assert "120" in denied.technical


def test_win32_and_installer_codes_explain_the_next_step() -> None:
    assert win32(32).failure is Failure.IN_USE
    assert win32(5).failure is Failure.NEEDS_ADMIN
    assert installer_exit(1618).failure is Failure.BUSY
    assert installer_exit(3010).failure is Failure.REBOOT
    unknown = installer_exit(4242)
    assert unknown.failure is Failure.OTHER
    assert "4242" in unknown.technical


def test_leftover_rows_say_what_each_one_is() -> None:
    row = Leftover("value", r"HKCU\SOFTWARE\Run|Demo", "Arranca con Windows").row()
    assert row["kind"] == "Inicio automático"
    assert row["path"] == r"HKCU\SOFTWARE\Run → Demo"
    assert row["id"] == r"value|HKCU\SOFTWARE\Run|Demo"


def test_hkcu_of_another_user_goes_through_hku() -> None:
    other = UserSession(
        sid="S-1-5-21-1-2-3-1001",
        profile=r"C:\Users\Ficticio",
        appdata=r"C:\Users\Ficticio\AppData\Roaming",
        local_appdata=r"C:\Users\Ficticio\AppData\Local",
        desktop=r"C:\Users\Ficticio\Desktop",
    )
    assert user_registry_key(r"HKCU\SOFTWARE\Demo", other) == (
        r"HKU\S-1-5-21-1-2-3-1001\SOFTWARE\Demo"
    )
    assert user_registry_key(r"HKLM\SOFTWARE\Demo", other) == r"HKLM\SOFTWARE\Demo"
    assert user_registry_key(r"HKCU\SOFTWARE\Demo", None) == r"HKCU\SOFTWARE\Demo"


def test_count_phrase_reads_naturally() -> None:
    assert count_phrase(["folder"]) == "1 carpeta"
    assert count_phrase(["folder", "folder", "key"]) == "2 carpetas y 1 clave del Registro"
    assert count_phrase(["service", "task", "firewall"]) == (
        "1 servicio, 1 tarea programada y 1 regla del firewall"
    )

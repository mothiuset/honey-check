"""Identidad estable de un equipo, con datos ficticios."""

from __future__ import annotations

from typing import Any

import pytest

from fakes import FakeCim, make_context, make_ports
from fixtures.vendors import ACER, HP, PCSMART
from honey_check.domain.identity import IdentityBasis, device_key
from honey_check.domain.inventory import SCHEMA_VERSION
from honey_check.domain.migrations import upgrade
from honey_check.infrastructure.collectors.hardware import IdentityCollector


def identity(rows: dict[str, Any]) -> Any:
    return IdentityCollector().collect(make_context(make_ports(cim=FakeCim(rows))))


def test_uuid_is_preferred() -> None:
    assert device_key(identity(HP)).basis is IdentityBasis.SMBIOS_UUID


def test_key_is_stable_and_differs_between_devices() -> None:
    assert device_key(identity(HP)) == device_key(identity(HP))
    assert device_key(identity(HP)) != device_key(identity(ACER))


def test_key_survives_a_hostname_change() -> None:
    renamed = {**HP, "Win32_ComputerSystem": [{**HP["Win32_ComputerSystem"][0], "Name": "OTRO"}]}
    assert device_key(identity(HP)) == device_key(identity(renamed))


def test_key_does_not_contain_the_serial() -> None:
    key = device_key(identity(HP)).value
    assert "HP-SERIE" not in key
    assert len(key) == 24


@pytest.mark.parametrize(
    "shared_uuid",
    ["03000200-0400-0500-0006-000700080009", "00000000-0000-0000-0000-000000000000"],
)
def test_shared_or_null_uuid_falls_back_to_serial(shared_uuid: str) -> None:
    rows = {**HP, "Win32_ComputerSystemProduct": [{"IdentifyingNumber": "X", "UUID": shared_uuid}]}
    assert device_key(identity(rows)).basis is IdentityBasis.SERIAL


def test_assembled_pc_with_fillers_uses_baseboard_or_hostname() -> None:
    key = device_key(identity(PCSMART))
    assert key.basis in (IdentityBasis.BASEBOARD_SERIAL, IdentityBasis.HOSTNAME)


def test_nothing_known_is_unknown() -> None:
    assert device_key(None).basis is IdentityBasis.UNKNOWN


def test_migration_from_1_0_0_adds_identity() -> None:
    document = {
        "schema": {"name": "honey-check.inventory", "version": "1.0.0"},
        "collection": {"inventoryId": "x"},
        "device": None,
    }
    upgraded = upgrade(document)
    assert upgraded["schema"]["version"] == SCHEMA_VERSION
    assert upgraded["collection"]["deviceKey"] == "sin-identificar"
    assert upgraded["peripherals"] is None
    assert upgraded["collection"]["sequence"] is None


def test_migration_from_2_0_0_marks_peripherals_as_not_collected() -> None:
    document = {
        "schema": {"name": "honey-check.inventory", "version": "2.0.0"},
        "collection": {"inventoryId": "x"},
        "device": None,
    }
    upgraded = upgrade(document)
    assert upgraded["schema"]["version"] == SCHEMA_VERSION
    assert upgraded["peripherals"] is None

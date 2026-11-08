"""Reglas de dominio: con datos ficticios y sin tocar Windows."""

from datetime import datetime

import pytest
from pydantic import ValidationError

from honey_check.domain.classification import (
    DeviceType,
    DiskBus,
    DiskKind,
    classify_disk,
    decode_antivirus_state,
    device_type,
    exclusion_reason,
    is_ltsc_edition,
    memory_type_from_smbios,
    pnp_says_usb,
    windows_generation,
)
from honey_check.domain.inventory import PathEvidence, PathState
from honey_check.domain.migrations import UnsupportedSchemaError, upgrade
from honey_check.domain.naming import inventory_stem, is_valid_inventory_id, safe_hostname
from honey_check.domain.normalize import (
    observed_positive_int,
    observed_text,
    parse_yyyymmdd,
)
from honey_check.domain.observed import Confidence, Observed, Reason


class TestObserved:
    def test_present_value_requires_source(self) -> None:
        with pytest.raises(ValidationError):
            Observed[str](value="x", confidence=Confidence.REPORTED)

    def test_null_value_cannot_claim_confidence(self) -> None:
        with pytest.raises(ValidationError):
            Observed[str](value=None, confidence=Confidence.REPORTED, source="s", reason="r")

    def test_unknown_requires_reason(self) -> None:
        with pytest.raises(ValidationError):
            Observed[str](value=None)

    def test_factories(self) -> None:
        assert Observed[str].reported("a", "wmi").confidence is Confidence.REPORTED
        assert Observed[str].probable("a", "h").confidence is Confidence.PROBABLE
        unknown = Observed[str].unknown(Reason.ACCESS_DENIED)
        assert unknown.value is None
        assert unknown.reason == Reason.ACCESS_DENIED


class TestNormalize:
    @pytest.mark.parametrize(
        "raw",
        [
            "To be filled by O.E.M.",
            "Default string",
            "System Serial Number",
            "  None ",
            "0000000000",
            "FFFFFFFF",
            "00000000-0000-0000-0000-000000000000",
        ],
    )
    def test_placeholders_become_unknown_and_keep_raw(self, raw: str) -> None:
        result = observed_text(raw, "wmi:x")
        assert result.value is None
        assert result.reason == Reason.PLACEHOLDER
        assert result.raw == raw.strip()

    def test_real_value_is_trimmed(self) -> None:
        result = observed_text("  TEST-SERIAL-0001  ", "wmi:x")
        assert result.value == "TEST-SERIAL-0001"
        assert result.confidence is Confidence.REPORTED

    def test_missing_text_is_not_reported(self) -> None:
        assert observed_text(None, "s").reason == Reason.NOT_REPORTED
        assert observed_text("   ", "s").reason == Reason.NOT_REPORTED

    @pytest.mark.parametrize("raw", [None, 0, -1, True])
    def test_zero_is_not_a_measurement(self, raw: object) -> None:
        assert observed_positive_int(raw, "s").value is None

    def test_invalid_int_keeps_raw(self) -> None:
        result = observed_positive_int("abc", "s")
        assert result.reason == Reason.INVALID_VALUE
        assert result.raw == "abc"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("20260115", "2026-01-15"), ("20261345", None), ("2026-01-15", None), ("", None)],
    )
    def test_install_date(self, raw: str, expected: str | None) -> None:
        assert parse_yyyymmdd(raw) == expected


class TestDiskClassification:
    @pytest.mark.parametrize(
        ("bus", "media", "spindle", "expected"),
        [
            (DiskBus.NVME, 4, 0, DiskKind.SSD_NVME),
            (DiskBus.NVME, 0, None, DiskKind.SSD_NVME),
            (DiskBus.SATA, 4, 0, DiskKind.SSD_SATA),
            (DiskBus.ATA, 4, 0, DiskKind.SSD_SATA),
            (DiskBus.SATA, 3, 7200, DiskKind.HDD),
            (DiskBus.SATA, 0, 5400, DiskKind.HDD),
            (DiskBus.SAS, 4, 0, DiskKind.SSD_SAS),
            (DiskBus.MMC, 0, None, DiskKind.EMMC),
            (DiskBus.RAID, 4, 0, DiskKind.SSD_OTHER),
        ],
    )
    def test_known(self, bus: DiskBus, media: int, spindle: int | None, expected: DiskKind) -> None:
        assert classify_disk(bus, media, spindle).kind is expected

    @pytest.mark.parametrize("spindle", [None, 0, 0xFFFFFFFF])
    def test_uncertain_is_declared(self, spindle: int | None) -> None:
        result = classify_disk(DiskBus.SATA, 0, spindle)
        assert result.kind is None
        assert result.rule == "media_type_unspecified"

    @pytest.mark.parametrize("bus", [DiskBus.USB, DiskBus.SD, DiskBus.FILE_BACKED_VIRTUAL])
    def test_external_buses_are_excluded(self, bus: DiskBus) -> None:
        assert exclusion_reason(bus) is not None

    @pytest.mark.parametrize("bus", [DiskBus.NVME, DiskBus.SATA, DiskBus.ATA, DiskBus.MMC])
    def test_internal_buses_are_kept(self, bus: DiskBus) -> None:
        assert exclusion_reason(bus) is None

    def test_usb_by_pnp(self) -> None:
        assert pnp_says_usb("USBSTOR\\DISK&VEN_FICTICIO&PROD_X\\123")
        assert not pnp_says_usb("SCSI\\DISK&VEN_NVME&PROD_X\\5&1")
        assert not pnp_says_usb(None)


class TestMemoryType:
    @pytest.mark.parametrize(
        ("code", "expected"),
        [(24, "DDR3"), (26, "DDR4"), (34, "DDR5"), (30, "LPDDR4"), (35, "LPDDR5")],
    )
    def test_known_codes(self, code: int, expected: str) -> None:
        assert memory_type_from_smbios(code) == expected

    @pytest.mark.parametrize("code", [None, 0, 2, 99])
    def test_unknown_codes_are_not_guessed(self, code: int | None) -> None:
        assert memory_type_from_smbios(code) is None


class TestDeviceType:
    def test_chassis_wins(self) -> None:
        assert device_type([10], 1, "X")[0] is DeviceType.LAPTOP

    def test_falls_back_to_pc_system_type(self) -> None:
        assert device_type([2], 1, "X")[0] is DeviceType.DESKTOP

    def test_virtual_machine(self) -> None:
        assert device_type([3], 1, "VMware Virtual Platform")[0] is DeviceType.VIRTUAL_MACHINE

    def test_unknown(self) -> None:
        assert device_type([2], None, None) == (None, None)


class TestOperatingSystemRules:
    @pytest.mark.parametrize(
        ("build", "expected"),
        [(19045, "windows_10"), (22000, "windows_11"), (26100, "windows_11"), (9600, "other")],
    )
    def test_generation_uses_build(self, build: int, expected: str) -> None:
        assert windows_generation(build) == expected

    @pytest.mark.parametrize(
        ("edition", "expected"),
        [
            ("IoTEnterpriseS", True),
            ("EnterpriseS", True),
            ("Enterprise", False),
            ("Professional", False),
            (None, None),
        ],
    )
    def test_ltsc(self, edition: str | None, expected: bool | None) -> None:
        assert is_ltsc_edition(edition) is expected


class TestAntivirusState:
    def test_enabled_and_current(self) -> None:
        assert decode_antivirus_state(0x061100) == (True, True)

    def test_disabled_and_outdated(self) -> None:
        assert decode_antivirus_state(0x060010) == (False, False)

    def test_unknown(self) -> None:
        assert decode_antivirus_state(None) == (None, None)


class TestNaming:
    def test_example_format(self) -> None:
        moment = datetime(2026, 11, 4, 10, 30, 0)  # noqa: DTZ001
        assert inventory_stem("PC-DEAJ-001", moment) == "honey-check_PC-DEAJ-001_2026-11-04_103000"

    def test_sequence_avoids_collision(self) -> None:
        moment = datetime(2026, 11, 4, 10, 30, 0)  # noqa: DTZ001
        assert inventory_stem("PC", moment, 2).endswith("_103000_02")

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("..\\..\\evil", "evil"),
            ("a/b:c", "a_b_c"),
            ("", "equipo-sin-nombre"),
            (None, "equipo-sin-nombre"),
            ("CON", "equipo-sin-nombre"),
            ("ñandú", "and"),
        ],
    )
    def test_hostname_is_sanitized(self, raw: str | None, expected: str) -> None:
        assert safe_hostname(raw) == expected

    @pytest.mark.parametrize(
        ("value", "valid"),
        [
            ("honey-check_PC-1_2026-11-04_103000", True),
            ("honey-check_..\\evil", False),
            ("honey-check_../evil", False),
            ("honey-check_a..b", False),
            ("other_file", False),
        ],
    )
    def test_inventory_id(self, value: str, valid: bool) -> None:
        assert is_valid_inventory_id(value) is valid


class TestPathEvidence:
    def test_null_path_requires_reason(self) -> None:
        with pytest.raises(ValidationError):
            PathEvidence()

    def test_present_path_requires_source(self) -> None:
        with pytest.raises(ValidationError):
            PathEvidence(value="C:\\x", confidence=Confidence.REPORTED, state=PathState.VALID)


class TestSchemaUpgrade:
    def test_rejects_foreign_document(self) -> None:
        with pytest.raises(UnsupportedSchemaError):
            upgrade({"hello": "world"})

    def test_rejects_future_schema(self) -> None:
        document = {"schema": {"name": "honey-check.inventory", "version": "99.0.0"}}
        with pytest.raises(UnsupportedSchemaError, match="más reciente"):
            upgrade(document)

    def test_rejects_malformed_version(self) -> None:
        document = {"schema": {"name": "honey-check.inventory", "version": "uno"}}
        with pytest.raises(UnsupportedSchemaError, match="inválida"):
            upgrade(document)

    def test_rejects_version_without_migration(self) -> None:
        document = {"schema": {"name": "honey-check.inventory", "version": "0.9.0"}}
        with pytest.raises(UnsupportedSchemaError, match="no hay migración"):
            upgrade(document)

    def test_applies_migration_chain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from honey_check.domain import migrations
        from honey_check.domain.inventory import SCHEMA_VERSION

        def step(document: dict) -> dict:  # type: ignore[type-arg]
            return {
                **document,
                "migrated": True,
                "schema": {**document["schema"], "version": SCHEMA_VERSION},
            }

        monkeypatch.setitem(migrations.MIGRATIONS, "0.9.0", step)
        document = {"schema": {"name": "honey-check.inventory", "version": "0.9.0"}}
        assert upgrade(document)["migrated"] is True

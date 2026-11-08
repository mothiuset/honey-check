"""Export policy with fictional paths only; never probe a real network share."""

from pathlib import Path
from unittest.mock import Mock

import pytest

from honey_check.application import service as service_module
from honey_check.application.service import (
    AlternateDirectoryRejected,
    InventoryService,
    validate_alternate_directory,
)
from honey_check.composition import is_network_export_path
from honey_check.infrastructure.windows import files


def test_mapped_network_drive_rejected_before_any_directory_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup = Mock(side_effect=AssertionError("Must not probe a network directory"))
    monkeypatch.setattr(service_module, "_is_directory", lookup)
    policy = Mock(return_value=True)
    with pytest.raises(AlternateDirectoryRejected, match="network_path_not_allowed"):
        validate_alternate_directory(r"Z:\fictional-inventories", policy)
    policy.assert_called_once_with(r"Z:\fictional-inventories")
    lookup.assert_not_called()


def test_rejected_network_destination_never_reaches_writable_probe_or_store() -> None:
    store = Mock()
    writable = Mock()
    service = InventoryService(store, Mock(), writable, is_network_path=lambda _: True)
    with pytest.raises(AlternateDirectoryRejected, match="network_path_not_allowed"):
        service.export_pending_to(r"Z:\fictional-inventories")
    writable.assert_not_called()
    store.save.assert_not_called()
    store.use_directory.assert_not_called()


@pytest.mark.parametrize("drive_type", [2, 3])
def test_local_fixed_and_removable_export_destinations_remain_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, drive_type: int
) -> None:
    query = Mock(return_value=drive_type)
    monkeypatch.setattr(files._kernel32, "GetDriveTypeW", query)
    assert validate_alternate_directory(str(tmp_path), is_network_export_path) == tmp_path
    query.assert_called_once_with(tmp_path.drive + "\\")


def test_composition_uses_native_drive_type_for_letter_mapped_share(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = Mock(return_value=4)
    monkeypatch.setattr(files._kernel32, "GetDriveTypeW", query)
    lookup = Mock(side_effect=AssertionError("Network lookup forbidden"))
    monkeypatch.setattr(service_module, "_is_directory", lookup)
    with pytest.raises(AlternateDirectoryRejected, match="network_path_not_allowed"):
        validate_alternate_directory(r"Z:\fictional-inventories", is_network_export_path)
    query.assert_called_once_with("Z:\\")
    lookup.assert_not_called()


def test_unobservable_network_policy_fails_without_lookup_or_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup = Mock()
    monkeypatch.setattr(service_module, "_is_directory", lookup)
    with pytest.raises(OSError, match="fictional policy failure"):
        validate_alternate_directory(
            r"Z:\fictional-inventories", Mock(side_effect=OSError("fictional policy failure"))
        )
    lookup.assert_not_called()

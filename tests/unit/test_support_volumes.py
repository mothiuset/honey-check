"""Analizar espacio de varias unidades y elegirlas por disco físico."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from honey_check.application.ports import CancelToken
from honey_check.application.support.context import RunContext
from honey_check.application.support.ports import CommandOutput, SupportEnvironment
from honey_check.domain.support import ChartKind
from honey_check.infrastructure.support.tools import disk
from honey_check.infrastructure.windows.volumes import Disk, Partition


class _Runner:
    def run(self, args: Any, **_: Any) -> CommandOutput:
        return CommandOutput(0, "", "")


def _context(tmp_path: Path) -> RunContext:
    env = SupportEnvironment(tmp_path / "datos", _Runner(), False, None)
    (tmp_path / "datos").mkdir()
    return RunContext(env, CancelToken(), "prueba", lambda: None)


def _tree(root: Path, files: dict[str, int]) -> Path:
    for relative, size in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\0" * size)
    return root


def test_several_roots_are_scanned_and_merged(tmp_path: Path) -> None:
    first = _tree(tmp_path / "Uno", {"fotos/a.jpg": 4000, "b.txt": 10})
    second = _tree(tmp_path / "Dos", {"videos/c.mp4": 9000})
    result = disk._analyze(  # noqa: SLF001 - se prueba la ejecución sin la validación de rutas
        {"targets": [str(first)], "path": str(second)}, _context(tmp_path)
    )
    tree = result.charts[0]
    assert tree.kind is ChartKind.TREEMAP
    root = tree.data[0]
    assert root["name"] == "Unidades elegidas"
    assert [child["name"] for child in root["children"]] == ["Dos", "Uno"]
    assert root["value"] == 13010
    files = result.tables[0].rows
    assert files[0]["name"] == "c.mp4"
    # Con varias raíces, la carpeta dice de cuál es.
    assert files[0]["folder"] == str(second / "videos")


def test_nothing_chosen_is_explained(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Elija al menos una unidad"):
        disk._analyze({"targets": [], "path": None}, _context(tmp_path))  # noqa: SLF001


def test_choices_group_partitions_by_physical_disk(monkeypatch: pytest.MonkeyPatch) -> None:
    gib = 1024**3
    monkeypatch.setattr(
        disk,
        "list_disks",
        lambda: [
            Disk(
                0,
                "Disco ficticio",
                500 * gib,
                "NVMe",
                "SSD",
                "Saludable",
                True,
                [
                    Partition(1, 300 * gib, "C", "Windows", "NTFS", 30 * gib),
                    Partition(2, 1 * gib, None, None, "NTFS", None, "Recuperación de Windows"),
                ],
            ),
            Disk(
                1,
                "USB ficticia",
                64 * gib,
                "USB",
                None,
                None,
                False,
                [Partition(1, 64 * gib, "E", "DATOS", "exFAT", 60 * gib)],
            ),
        ],
    )
    choices = disk.volume_choices()
    assert [c.value for c in choices] == ["C:\\", "particion-0-2", "E:\\"]
    system, reserved, usb = choices
    assert system.group == "Disco 0: Disco ficticio (NVMe SSD), 500.0 GiB, saludable"
    assert system.label == "C: Windows" and system.used == 0.9
    assert reserved.disabled_reason and "no se analiza" in reserved.disabled_reason
    assert usb.group and usb.group.startswith("Disco 1: USB ficticia (USB)")


def test_system_folders_say_what_they_are() -> None:
    bin_node = disk._with_folder_actions(  # noqa: SLF001
        {"name": "$RECYCLE.BIN", "path": "D:\$RECYCLE.BIN", "value": 10}
    )
    assert bin_node["detail"] == "Papelera de reciclaje de esta unidad"
    assert [a["tool"] for a in bin_node["actions"]] == ["files.empty_recycle_bin"]
    svi = disk._with_folder_actions(  # noqa: SLF001
        {"name": "System Volume Information", "path": "C:\System Volume Information", "value": 1}
    )
    assert svi["actions"] == [] and "Protección del sistema" in svi["detail"]

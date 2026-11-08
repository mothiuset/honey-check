"""Versiones de las ejecuciones: comprimidas, listables sin abrirlas y cargables completas."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from honey_check.domain.support import (
    Chart,
    ChartKind,
    Risk,
    Run,
    RunStatus,
    ToolResult,
)
from honey_check.infrastructure.support.base import fact
from honey_check.infrastructure.support.journal import FileRunJournal


def _run(run_id: str, tool: str, minutes_ago: int, size: int) -> Run:
    tree = {
        "name": "C:",
        "value": size,
        "children": [{"name": f"c{i}", "value": i} for i in range(2000)],
    }
    return Run(
        id=run_id,
        plan_id="p" * 24,
        tool=tool,
        title="Analizar espacio",
        risk=Risk.READ,
        params={"targets": ["C:\\"]},
        status=RunStatus.SUCCEEDED,
        started_at=datetime.now(UTC) - timedelta(minutes=minutes_ago),
        result=ToolResult(
            summary=[fact("Tamaño", size)],
            charts=[Chart(id="arbol", title="Espacio", kind=ChartKind.TREEMAP, data=[tree])],
        ),
    )


def test_versions_are_compressed_listed_light_and_loaded_full(tmp_path: Path) -> None:
    journal = FileRunJournal(lambda: tmp_path)
    journal.save(_run("aaaa1111", "disk.analyze", 30, 100))
    journal.save(_run("bbbb2222", "disk.analyze", 5, 120))
    journal.save(_run("cccc3333", "network.connectivity", 1, 1))

    files = sorted(p.name for p in (tmp_path / "acciones").glob("*.gz"))
    assert len(files) == 3
    raw = len(_run("x", "disk.analyze", 0, 1).model_dump_json())
    assert all((tmp_path / "acciones" / f).stat().st_size < raw / 4 for f in files)

    versions = journal.recent(10, "disk.analyze")
    assert [v.id for v in versions] == ["bbbb2222", "aaaa1111"]
    assert versions[0].result is not None
    assert versions[0].result.summary[0].value == "120"
    assert versions[0].result.charts == []  # liviana: sin el árbol

    full = journal.load("aaaa1111")
    assert full is not None and full.result is not None
    assert len(full.result.charts[0].data[0]["children"]) == 2000


def test_records_from_before_the_index_are_still_read(tmp_path: Path) -> None:
    folder = tmp_path / "acciones"
    folder.mkdir()
    old = _run("dddd4444", "disk.analyze", 60, 7)
    (folder / f"{old.started_at:%Y%m%dT%H%M%SZ}_disk.analyze_dddd4444.json").write_text(
        old.model_dump_json(by_alias=True), encoding="utf-8"
    )
    journal = FileRunJournal(lambda: tmp_path)
    journal.save(_run("eeee5555", "disk.analyze", 1, 8))
    assert [v.id for v in journal.recent(10, "disk.analyze")] == ["eeee5555", "dddd4444"]
    loaded = journal.load("dddd4444")
    assert loaded is not None and loaded.result is not None and loaded.result.charts


def test_load_rejects_odd_identifiers(tmp_path: Path) -> None:
    assert FileRunJournal(lambda: tmp_path).load("../../x") is None

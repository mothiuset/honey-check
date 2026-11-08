"""Herramientas de soporte contra el Windows real, solo sobre objetivos que crea la propia prueba.

Lectura: cada herramienta visible de solo lectura termina y devuelve algo con sentido.
Cambios: una clave ficticia en HKCU y una credencial ficticia, que la prueba crea y elimina.
"""

from __future__ import annotations

import secrets
import subprocess
import time
import winreg
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from honey_check.composition import support_services
from honey_check.domain.support import Risk, Run, RunStatus
from honey_check.infrastructure.windows.credentials import list_credentials
from honey_check.infrastructure.windows.process import ProcessRunner

pytestmark = pytest.mark.windows_real

CMDKEY = r"C:\Windows\System32\cmdkey.exe"


@pytest.fixture
def support(tmp_path: Path) -> Iterator[Any]:
    engine, procedures = support_services(lambda: tmp_path, ProcessRunner(), lambda: (False, None))
    yield engine, procedures, tmp_path
    engine.shutdown()


def _run(engine: Any, tool: str, params: dict[str, Any], *, confirmed: bool = False) -> Run:
    plan = engine.plan(tool, params)
    run = engine.start(plan.id, confirmed=confirmed)
    deadline = time.monotonic() + 180
    while (run := engine.snapshot(run.id)).status is RunStatus.RUNNING:
        assert time.monotonic() < deadline, f"{tool} no terminó"
        time.sleep(0.05)
    return run


@pytest.mark.parametrize(
    ("tool", "params"),
    [
        ("network.diagnose", {}),
        ("network.ping", {"host": "127.0.0.1"}),
        ("network.port", {"host": "127.0.0.1", "port": 135}),
        ("domain.diagnose", {}),
        ("printers.list", {}),
        ("printers.drivers", {}),
        ("certs.list", {}),
        ("services.list", {}),
        ("processes.list", {}),
        ("startup.list", {}),
        ("system.events", {}),
        ("registry.browse", {"key": "HKCU\\Software"}),
        ("credentials.list", {}),
        ("cleanup.preview", {}),
    ],
)
def test_read_tools_finish_on_this_machine(support: Any, tool: str, params: dict[str, Any]) -> None:
    engine, _, data = support
    run = _run(engine, tool, params)
    assert run.status in (RunStatus.SUCCEEDED, RunStatus.PARTIAL), run.error
    assert run.result is not None
    assert run.result.summary or run.result.checks or run.result.tables
    assert any(data.joinpath("acciones").glob(f"*_{tool}_{run.id}.json*"))


def test_disk_analysis_of_a_folder_created_by_the_test(support: Any, tmp_path: Path) -> None:
    engine, _, _ = support
    folder = tmp_path / "analizar"
    (folder / "grande").mkdir(parents=True)
    (folder / "grande" / "archivo.bin").write_bytes(b"\0" * 300_000)
    (folder / "chico.txt").write_bytes(b"x" * 10)
    run = _run(engine, "disk.analyze", {"path": str(folder)})
    assert run.status is RunStatus.SUCCEEDED
    assert run.result is not None
    tree = run.result.charts[0].data[0]
    assert tree["children"][0]["name"] == "grande"
    files = run.result.tables[0]
    assert str(files.rows[0]["path"]).endswith("archivo.bin")
    # La carpeta se muestra relativa a lo analizado: la ruta completa no se repite en cada fila.
    assert files.rows[0]["folder"] == "grande"


@pytest.fixture
def fictitious_key() -> Iterator[str]:
    sub = f"Software\\HoneyCheckPrueba-{secrets.token_hex(4)}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, sub + "\\Hija") as key:
        winreg.SetValueEx(key, "Texto", 0, winreg.REG_SZ, "valor ficticio")
    yield f"HKCU\\{sub}"
    subprocess.run(["reg.exe", "delete", f"HKCU\\{sub}", "/f"], capture_output=True, check=False)


def _exists(sub: str) -> bool:
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub))
    except OSError:
        return False
    return True


def test_registry_set_export_and_delete_with_backup(support: Any, fictitious_key: str) -> None:
    engine, _, data = support
    sub = fictitious_key.split("\\", 1)[1]
    set_run = _run(
        engine,
        "registry.set",
        {"key": fictitious_key, "name": "Numero", "kind": "REG_DWORD", "data": "0x2A"},
        confirmed=True,
    )
    assert set_run.status is RunStatus.SUCCEEDED, set_run.error
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub) as key:
        assert winreg.QueryValueEx(key, "Numero") == (42, winreg.REG_DWORD)
    export = _run(engine, "registry.export", {"key": fictitious_key})
    assert export.status is RunStatus.SUCCEEDED
    exported = Path(export.result.files[0].path)  # type: ignore[union-attr]
    assert "valor ficticio" in exported.read_text(encoding="utf-16")
    with pytest.raises(PermissionError):
        engine.plan(
            "registry.set",
            {
                "key": r"HKCU\Software\Policies\HoneyCheckPrueba",
                "name": "x",
                "kind": "REG_SZ",
                "data": "y",
            },
        )
    deleted = _run(engine, "registry.delete", {"key": fictitious_key, "value": ""}, confirmed=True)
    assert deleted.status is RunStatus.SUCCEEDED, deleted.error
    assert deleted.result is not None and deleted.result.verified
    assert not _exists(sub)
    assert any((data / "respaldos").rglob("*.reg"))


def test_credential_delete_on_a_fictitious_credential(support: Any) -> None:
    engine, _, _ = support
    target = f"HoneyCheckPrueba-{secrets.token_hex(4)}"
    subprocess.run(
        [CMDKEY, f"/generic:{target}", "/user:ficticio", "/pass:no-es-real"],
        capture_output=True,
        check=True,
    )
    try:
        listed = _run(engine, "credentials.list", {"filter": target.lower()})
        rows = listed.result.tables[0].rows  # type: ignore[union-attr]
        assert [r["target"] for r in rows] == [target]
        assert "no-es-real" not in listed.model_dump_json()
        run = _run(
            engine,
            "credentials.delete",
            {"target": target, "type": str(rows[0]["type"])},
            confirmed=True,
        )
        assert run.status is RunStatus.SUCCEEDED, run.error
        assert all(c.target != target for c in list_credentials())
    finally:
        subprocess.run([CMDKEY, f"/delete:{target}"], capture_output=True, check=False)


def test_procedure_with_automatic_and_manual_steps(support: Any, tmp_path: Path) -> None:
    engine, procedures, _ = support
    marker = tmp_path / "marca.txt"
    marker.write_text("ficticio", encoding="utf-8")
    procedures.save(
        {
            "slug": "prueba-real",
            "name": "Prueba real",
            "steps": [
                {
                    "id": "archivo",
                    "kind": "verify_file",
                    "title": "Archivo",
                    "params": {"path": str(marker)},
                },
                {
                    "id": "servicio",
                    "kind": "verify_service",
                    "title": "Servicio de eventos",
                    "params": {"name": "EventLog"},
                },
                {
                    "id": "comando",
                    "kind": "command",
                    "title": "Nombre del equipo",
                    "params": {"command": r"C:\Windows\System32\hostname.exe"},
                },
                {"id": "manual", "kind": "manual", "title": "Revisión del técnico"},
            ],
        }
    )
    run = _run(engine, "procedure.run", {"procedure": "prueba-real"}, confirmed=True)
    assert run.status is RunStatus.SUCCEEDED, run.error
    rows = {r["id"]: r["state"] for r in run.result.tables[0].rows}  # type: ignore[union-attr]
    assert rows == {
        "archivo": "Hecho",
        "servicio": "Hecho",
        "comando": "Hecho",
        "manual": "Espera al técnico",
    }
    run_id = run.result.tables[1].rows[0]["run"]  # type: ignore[union-attr]
    marked = _run(engine, "procedure.mark", {"run": run_id, "step": "manual", "state": "ok"})
    assert marked.result is not None and marked.result.verified is True


def test_every_visible_tool_plans_with_its_defaults(support: Any) -> None:
    """El plan de lo que se puede abrir desde el catálogo se arma sin ejecutar nada."""
    engine, _, _ = support
    for definition in engine.catalog():
        if definition.hidden or any(p.required and p.default is None for p in definition.params):
            continue
        plan = engine.plan(definition.id, {})
        assert plan.steps, definition.id
        if definition.risk is not Risk.READ:
            assert plan.risk is definition.risk

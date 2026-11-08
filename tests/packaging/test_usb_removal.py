"""Desaparición de la unidad con el .exe real en marcha.

Se monta la carpeta como una unidad con `subst` y se retira la letra durante la ejecución. No
equivale a extraer físicamente una USB: ahí Windows puede invalidar páginas del ejecutable que
aún no estén en memoria, y ese caso no puede reproducirse sin hardware.
"""

from __future__ import annotations

import shutil
import string
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from test_executable import (
    EXE_ENV,
    SCAN_TIMEOUT_S,
    Running,
    authenticated_opener,
    kill_tree,
    launch,
    wait_for_file,
)

pytestmark = pytest.mark.packaging

SUBST = r"C:\Windows\System32\subst.exe"


def free_drive_letter() -> str:
    for letter in reversed(string.ascii_uppercase):
        if not Path(f"{letter}:\\").exists():
            return letter
    pytest.skip("No hay letras de unidad libres")


@pytest.fixture
def mounted(exe_copy_root: Path) -> Iterator[tuple[str, Path]]:
    if not EXE_ENV:
        pytest.skip("HONEY_CHECK_EXE no está definido")
    folder = exe_copy_root / "contenido-usb"
    shutil.copytree(Path(EXE_ENV).parent, folder, ignore=shutil.ignore_patterns("HoneyCheck-datos"))
    letter = free_drive_letter()
    subprocess.run([SUBST, f"{letter}:", str(folder)], check=True, capture_output=True)  # noqa: S603
    yield letter, folder
    subprocess.run([SUBST, f"{letter}:", "/D"], check=False, capture_output=True)  # noqa: S603


def test_unit_disappears_while_running_and_inventory_is_rescued(
    mounted: tuple[str, Path], tmp_path: Path
) -> None:
    letter, folder = mounted
    drive = Path(f"{letter}:\\")
    status_file = tmp_path / "estado.json"
    rescue = tmp_path / "rescate"
    rescue.mkdir()
    temp_dir = tmp_path / "temporales"
    temp_dir.mkdir()
    process = launch(drive / "HoneyCheck.exe", tmp_path, status_file, temp_dir)
    try:
        info = wait_for_file(status_file, process)
        base = f"http://127.0.0.1:{info['port']}"
        app = Running(
            process, folder, base, info["port"], authenticated_opener(info["url"]), temp_dir
        )
        _, session = app.request("/api/session")
        app.csrf = session["csrfToken"]

        # Los inventarios y los logs van a la unidad, no a una ruta resuelta de desarrollo.
        _, status = app.request("/api/status")
        assert status["workspace"]["directory"].upper().startswith(f"{letter}:")
        assert status["workspace"]["writable"] is True

        subprocess.run([SUBST, f"{letter}:", "/D"], check=True, capture_output=True)  # noqa: S603

        _, status = app.request("/api/status")
        assert status["workspace"]["available"] is False
        assert status["workspace"]["writable"] is False

        # El análisis sigue funcionando sin la unidad y conserva el resultado en memoria.
        code, _ = app.request("/api/scans", "POST")
        assert code == 202
        deadline = time.monotonic() + SCAN_TIMEOUT_S
        while time.monotonic() < deadline:
            _, status = app.request("/api/status")
            if status["scan"]["state"] not in ("running", "cancelling"):
                break
            time.sleep(1)
        assert status["scan"]["state"] == "finished", status["scan"]
        assert status["exportFailure"] is not None

        code, pending = app.request("/api/pending")
        assert code == 200
        assert pending["device"] is not None

        # Alternativa explícita: el técnico elige otra carpeta y el inventario se conserva.
        code, saved = app.request("/api/pending/export", "POST", {"directory": str(rescue)})
        assert code == 200
        saved_dir = Path(saved["directory"])
        assert saved_dir.is_relative_to(rescue / "HoneyCheck-datos")
        assert (saved_dir / saved["fileName"]).is_file()
        _, status = app.request("/api/status")
        assert status["exportFailure"] is None
        assert status["workspace"]["directory"] == str(rescue / "HoneyCheck-datos")

        code, _ = app.request("/api/exit", "POST")
        assert code == 202
        assert process.wait(45) == 0
    finally:
        kill_tree(process)

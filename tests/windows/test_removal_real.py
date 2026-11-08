"""Revisión previa y cierre de lo que usa un archivo, contra el Windows real (Restart Manager)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from honey_check.infrastructure.support.removal import inspect, needs_admin
from honey_check.infrastructure.windows.locks import (
    close_processes_using,
    processes_using,
    running_from,
)
from honey_check.infrastructure.windows.process import system32_path

pytestmark = pytest.mark.windows_real

_HOLD = (
    "import sys, time\n"
    "handle = open(sys.argv[1], 'a')\n"
    "print('listo', flush=True)\n"
    "time.sleep(60)\n"
)


def _holder(target: Path) -> subprocess.Popen[str]:
    """Un proceso aparte que deja el archivo abierto, como un programa que no se cerró."""
    # El python.exe de un entorno virtual puede ser un lanzador que abre otro proceso: se usa el
    # intérprete real para que el PID sea el que tiene el archivo abierto.
    python = getattr(sys, "_base_executable", sys.executable)
    process = subprocess.Popen(  # noqa: S603
        [python, "-c", _HOLD, str(target)],
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "listo"
    return process


def test_program_files_needs_admin_and_temp_does_not(tmp_path: Path) -> None:
    program_files = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
    assert needs_admin(program_files / "Programa Ficticio")
    assert not needs_admin(tmp_path)


def test_finds_and_closes_the_process_that_holds_a_file(tmp_path: Path) -> None:
    folder = tmp_path / "Programa Ficticio"
    folder.mkdir()
    target = folder / "datos.db"
    target.write_text("x", encoding="utf-8")
    holder = _holder(target)
    try:
        # Restart Manager ve también un archivo de datos abierto por un programa de otra carpeta.
        assert holder.pid in {p.pid for p in processes_using([str(folder)])}
        still = close_processes_using([str(folder)])
        assert holder.pid not in {p.pid for p in still}
        deadline = time.monotonic() + 15
        while holder.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert holder.poll() is not None
        assert not processes_using([str(folder)])
    finally:
        if holder.poll() is None:
            holder.kill()


def test_review_sees_a_program_running_from_the_folder(tmp_path: Path) -> None:
    """La revisión previa (rápida) detecta un ejecutable de la carpeta que está corriendo."""
    folder = tmp_path / "Programa Ficticio"
    folder.mkdir()
    program = folder / "ficticio.exe"
    program.write_bytes(system32_path("ping.exe").read_bytes())
    process = subprocess.Popen(  # noqa: S603
        [str(program), "-n", "30", "127.0.0.1"], stdout=subprocess.DEVNULL
    )
    try:
        deadline = time.monotonic() + 10
        while not running_from([str(folder)]) and time.monotonic() < deadline:
            time.sleep(0.1)
        assert process.pid in {p.pid for p in running_from([str(folder)])}
        review = inspect(folder)
        assert process.pid in {p.pid for p in review.in_use_by}
        assert review.check(elevated=False).status.value == "warn"
        assert "ficticio.exe" in (review.check(elevated=False).detail or "")
    finally:
        process.kill()
        process.wait(10)

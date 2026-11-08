"""Las copias del ejecutable van dentro del proyecto (build\pruebas-exe), nunca a %TEMP%: así se
prueba como en una USB, sin dejar nada fuera de la carpeta, y se borran al terminar."""

from __future__ import annotations

import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2] / "build" / "pruebas-exe"


@pytest.fixture
def exe_copy_root() -> Iterator[Path]:
    folder = _ROOT / uuid.uuid4().hex[:8]
    folder.mkdir(parents=True)
    yield folder
    shutil.rmtree(folder, ignore_errors=True)


@pytest.fixture(scope="module")
def exe_copy_root_module() -> Iterator[Path]:
    folder = _ROOT / uuid.uuid4().hex[:8]
    folder.mkdir(parents=True)
    yield folder
    shutil.rmtree(folder, ignore_errors=True)

"""El ejecutable lleva la interfaz dentro (`honey_check._bundle`); se sirve igual que desde disco."""

from __future__ import annotations

import io
import sys
import types
import zipfile
from collections.abc import Iterator

import pytest

from honey_check.presentation.http.app import static_files


def _archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


@pytest.fixture
def bundle() -> Iterator[types.ModuleType]:
    module = types.ModuleType("honey_check._bundle")
    module.COMPONENTS = "huella-ficticia"  # type: ignore[attr-defined]
    module.INTERFACE = _archive(  # type: ignore[attr-defined]
        {
            "index.html": b"<!doctype html><title>Honey Check</title>",
            "assets/index-abc123.js": b"console.log(1)",
            "assets/index-abc123.css": b"body{}",
            "icon.svg": b"<svg/>",
            "notas.txt": b"sin tipo publicado",
        }
    )
    sys.modules["honey_check._bundle"] = module
    yield module
    del sys.modules["honey_check._bundle"]


def test_serves_the_interface_from_the_executable(bundle: types.ModuleType) -> None:
    files = static_files()
    assert set(files) == {"/", "/assets/index-abc123.js", "/assets/index-abc123.css", "/icon.svg"}
    entry, media_type = files["/assets/index-abc123.js"]
    assert entry.read_bytes() == b"console.log(1)"
    assert media_type.startswith("text/javascript")
    assert files["/"][0].read_bytes().startswith(b"<!doctype html>")

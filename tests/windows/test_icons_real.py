"""Iconos de programas contra ejecutables reales de Windows, sin mocks."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from honey_check.infrastructure.windows.icons import ICON_SIZE, WinIconExtractor, encode_png
from honey_check.infrastructure.windows.process import system32_path

pytestmark = pytest.mark.windows_real


def png_size(data: bytes) -> tuple[int, int]:
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", data[16:24])


def test_encoder_produces_a_valid_png() -> None:
    data = encode_png(2, 1, bytes([255, 0, 0, 255, 0, 0, 255, 128]))
    assert png_size(data) == (2, 1)
    length = struct.unpack(">I", data[33:37])[0]
    pixels = zlib.decompress(data[41 : 41 + length])
    assert pixels == b"\x00" + bytes([255, 0, 0, 255, 0, 0, 255, 128])


def test_system_executable_icon() -> None:
    data = WinIconExtractor().executable_icon(str(system32_path("notepad.exe")))
    assert data is not None
    assert png_size(data) == (ICON_SIZE, ICON_SIZE)


def test_file_without_icon(tmp_path: Path) -> None:
    fake = tmp_path / "sin-icono.exe"
    fake.write_bytes(b"MZ" + b"\0" * 200)
    assert WinIconExtractor().executable_icon(str(fake)) is None
    assert WinIconExtractor().executable_icon(str(tmp_path / "no-existe.exe")) is None


def test_package_logo_picks_a_scaled_variant(tmp_path: Path) -> None:
    assets = tmp_path / "Assets"
    assets.mkdir()
    logo = encode_png(4, 4, bytes(64))
    (assets / "StoreLogo.scale-200.png").write_bytes(logo + b"x")
    (assets / "StoreLogo.scale-100.png").write_bytes(logo)
    (assets / "Otro.png").write_bytes(b"no")
    assert WinIconExtractor().package_logo(str(tmp_path), "Assets\\StoreLogo.png") == logo


@pytest.mark.parametrize("logo", ["..\\..\\Windows\\a.png", "C:\\Windows\\a.png"])
def test_package_logo_cannot_escape_the_package(tmp_path: Path, logo: str) -> None:
    assert WinIconExtractor().package_logo(str(tmp_path), logo) is None


def test_package_logo_rejects_non_png(tmp_path: Path) -> None:
    (tmp_path / "Logo.png").write_bytes(b"GIF89a")
    assert WinIconExtractor().package_logo(str(tmp_path), "Logo.png") is None

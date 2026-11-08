"""Firmas y almacenes de certificados contra el Windows real, sin red ni mocks."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from honey_check.application.ports import CancelToken
from honey_check.infrastructure.windows.crypt32 import list_certificates, signer_of
from honey_check.infrastructure.windows.process import system32_path
from honey_check.infrastructure.windows.wintrust import WinTrustSignatures, check_signature

pytestmark = pytest.mark.windows_real


def test_catalog_signed_system_binary() -> None:
    result = check_signature(str(system32_path("cmd.exe")))
    assert result.status == "valid"


def test_embedded_signature_reports_signer() -> None:
    signed = Path(sys.executable)
    result = check_signature(str(signed))
    if result.status != "valid" or result.signer == "Catálogo de Windows":
        pytest.skip("El intérprete de este entorno no trae firma incrustada")
    assert result.signer
    assert signer_of(str(signed)) == result.signer


def test_unsigned_file(tmp_path: Path) -> None:
    fake = tmp_path / "sin-firma.exe"
    fake.write_bytes(b"MZ" + b"\0" * 200)
    assert check_signature(str(fake)).status == "not_signed"
    assert signer_of(str(fake)) is None


def test_tampered_copy_is_detected(tmp_path: Path) -> None:
    original = Path(sys.executable).read_bytes()
    if check_signature(sys.executable).signer in (None, "Catálogo de Windows"):
        pytest.skip("Hace falta un ejecutable con firma incrustada")
    tampered = tmp_path / "alterado.exe"
    data = bytearray(original)
    data[len(data) // 3] ^= 0xFF
    tampered.write_bytes(bytes(data))
    assert check_signature(str(tampered)).status in ("hash_mismatch", "unknown_error", "not_signed")


def test_missing_file() -> None:
    assert check_signature("C:\\no-existe-honey-check.exe").status == "unknown_error"


def test_batch_is_fast_and_bounded() -> None:
    paths = [str(p) for p in system32_path().glob("*.exe")][:40]
    started = time.monotonic()
    found = WinTrustSignatures().inspect(paths, CancelToken(), 60)
    assert time.monotonic() - started < 30
    assert len(found) == len(paths)


def test_cancelled_batch_returns_quickly() -> None:
    token = CancelToken()
    token.cancel()
    paths = [str(p) for p in system32_path().glob("*.exe")][:40]
    assert WinTrustSignatures().inspect(paths, token, 60) == {}


def test_root_store_is_readable_without_elevation() -> None:
    records = list(list_certificates("CurrentUser", "Root"))
    assert records
    for record in records[:5]:
        assert len(record.thumbprint) == 40
        assert record.not_after > record.not_before
        assert record.der.startswith(b"0")

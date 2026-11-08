"""Conversión de valores WMI y respaldo por consulta entre vías, sin Windows real."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from honey_check.application.ports import CancelToken, CimError, CimErrorKind, CimQuery, CimResult
from honey_check.infrastructure.windows.com import ComError
from honey_check.infrastructure.windows.wmi import CimWithFallback, classify, convert, dmtf_to_iso


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("20240101123045.000000-300", "2024-01-01T17:30:45.000000Z"),
        ("20240101000000.500000+000", "2024-01-01T00:00:00.500000Z"),
        ("00000001000000.000000:000", None),  # intervalo, no fecha
        ("2024**01000000.000000+000", None),
        ("", None),
    ],
)
def test_dmtf_dates_become_utc_iso(raw: str, expected: str | None) -> None:
    assert dmtf_to_iso(raw) == expected


def test_unsigned_and_64_bit_integers() -> None:
    assert convert(-1, 19) == 2**32 - 1  # CIM_UINT32 llega como VT_I4
    assert convert("18446744073709551615", 21) == 2**64 - 1  # CIM_UINT64 llega como texto
    assert convert(["1", "2"], 21 | 0x2000) == [1, 2]
    assert convert("no-numero", 21) is None


def test_hresult_classification() -> None:
    assert classify(0x80041003) is CimErrorKind.ACCESS_DENIED
    assert classify(0x80041010) is CimErrorKind.NOT_AVAILABLE
    assert classify(0x800706BA) is CimErrorKind.TRANSIENT
    assert classify(0x80043001) is CimErrorKind.TIMEOUT
    assert classify(0x80004005) is CimErrorKind.FAILED


class Fake:
    def __init__(self, results: dict[str, CimResult], explode: bool = False) -> None:
        self.results = results
        self.explode = explode
        self.asked: list[str] = []

    def query(
        self, queries: Sequence[CimQuery], cancel: CancelToken, timeout_s: float
    ) -> list[CimResult]:
        if self.explode:
            raise ComError(-2147221164, "CoCreateInstance")
        self.asked.extend(q.class_name for q in queries)
        return [self.results[q.class_name] for q in queries]


def query(name: str) -> CimQuery:
    return CimQuery("root/cimv2", name, ("Name",))


def failed(kind: CimErrorKind) -> CimResult:
    return CimResult(error=CimError(kind, "x"))


def test_only_the_failed_query_goes_to_the_alternative() -> None:
    primary = Fake(
        {
            "Bien": CimResult(rows=({"Name": "com"},)),
            "Rota": failed(CimErrorKind.FAILED),
            "Lenta": failed(CimErrorKind.TIMEOUT),
            "Inexistente": failed(CimErrorKind.NOT_AVAILABLE),
            "Negada": failed(CimErrorKind.ACCESS_DENIED),
        }
    )
    fallback = Fake(
        {
            "Rota": CimResult(rows=({"Name": "ps"},)),
            "Lenta": CimResult(rows=({"Name": "ps"},)),
        }
    )
    names = ["Bien", "Rota", "Lenta", "Inexistente", "Negada"]
    results = CimWithFallback(primary, fallback).query([query(n) for n in names], CancelToken(), 30)
    assert fallback.asked == ["Rota", "Lenta"]  # lo inexistente o negado no se reintenta
    assert [r.rows[0]["Name"] if r.ok else r.error.kind for r in results] == [  # type: ignore[union-attr]
        "com",
        "ps",
        "ps",
        CimErrorKind.NOT_AVAILABLE,
        CimErrorKind.ACCESS_DENIED,
    ]


def test_whole_batch_moves_when_the_primary_cannot_start() -> None:
    fallback = Fake({"Bien": CimResult(rows=({"Name": "ps"},))})
    results = CimWithFallback(Fake({}, explode=True), fallback).query(
        [query("Bien")], CancelToken(), 30
    )
    assert results[0].rows == ({"Name": "ps"},)


def test_alternative_failure_keeps_the_original_error() -> None:
    primary = Fake({"Rota": failed(CimErrorKind.FAILED)})
    fallback = Fake({"Rota": failed(CimErrorKind.FAILED)})
    results = CimWithFallback(primary, fallback).query([query("Rota")], CancelToken(), 30)
    assert results[0].error is not None

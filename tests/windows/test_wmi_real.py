"""WMI por COM contra el Windows real: mismas filas que PowerShell, aislamiento y cancelación.

Los valores son datos reales de este equipo: se comparan entre vías, nunca se fijan aquí.
"""

from __future__ import annotations

import threading

import pytest

from honey_check.application.ports import CancelToken, CimErrorKind, CimQuery, CollectionCancelled
from honey_check.domain.normalize import parse_iso_datetime
from honey_check.infrastructure.windows.powershell import PowerShell, PowerShellCim
from honey_check.infrastructure.windows.process import ProcessRunner
from honey_check.infrastructure.windows.wmi import CimWithFallback, WmiCim

pytestmark = pytest.mark.windows_real


QUERIES = [
    CimQuery(
        "root/cimv2",
        "Win32_OperatingSystem",
        ("Caption", "LastBootUpTime", "TotalVisibleMemorySize"),
    ),
    CimQuery(
        "root/cimv2",
        "Win32_ComputerSystem",
        ("Manufacturer", "TotalPhysicalMemory", "PCSystemType"),
    ),
    CimQuery("root/cimv2", "Win32_Processor", ("Name", "NumberOfCores", "MaxClockSpeed")),
    CimQuery(
        "root/Microsoft/Windows/Storage", "MSFT_PhysicalDisk", ("FriendlyName", "Size", "BusType")
    ),
]


def normalized(rows: tuple[dict[str, object], ...]) -> list[dict[str, object]]:
    def value(item: object) -> object:
        moment = parse_iso_datetime(item) if isinstance(item, str) and item.endswith("Z") else None
        return moment or item

    return [{key: value(item) for key, item in row.items()} for row in rows]


def test_com_matches_powershell() -> None:
    com = WmiCim().query(QUERIES, CancelToken(), 60)
    runner = ProcessRunner()
    try:
        ps = PowerShellCim(PowerShell(runner)).query(QUERIES, CancelToken(), 90)
    finally:
        runner.close()
    for a, b in zip(com, ps, strict=True):
        assert a.ok, a.error
        assert normalized(a.rows) == normalized(b.rows)


def test_missing_class_and_namespace_are_isolated() -> None:
    results = WmiCim().query(
        [
            CimQuery("root/cimv2", "Win32_NoExisteHoneyCheck", ("Name",)),
            CimQuery("root/NoExisteHoneyCheck", "Win32_BIOS", ("Name",)),
            QUERIES[0],
        ],
        CancelToken(),
        30,
    )
    assert results[0].error is not None and results[0].error.kind is CimErrorKind.NOT_AVAILABLE
    assert results[1].error is not None and results[1].error.kind is CimErrorKind.NOT_AVAILABLE
    assert results[2].ok


def test_works_from_many_threads_at_once() -> None:
    errors: list[BaseException] = []

    def work() -> None:
        try:
            assert WmiCim().query(QUERIES[:2], CancelToken(), 60)[0].ok
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=work) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(90)
    assert errors == []


def test_cancelled_token_stops_the_query() -> None:
    token = CancelToken()
    token.cancel()
    with pytest.raises(CollectionCancelled):
        WmiCim().query(QUERIES, token, 30)


def test_rejects_injection() -> None:
    with pytest.raises(ValueError):
        WmiCim().query([CimQuery("root/cimv2", "Win32_BIOS", ("Name; DROP",))], CancelToken(), 5)


def test_fallback_composition_reads_everything() -> None:
    runner = ProcessRunner()
    try:
        cim = CimWithFallback(WmiCim(), PowerShellCim(PowerShell(runner)))
        assert all(result.ok for result in cim.query(QUERIES, CancelToken(), 60))
    finally:
        runner.close()

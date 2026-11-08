"""Dobles de los puertos para pruebas con mocks. Todos los datos son ficticios."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from honey_check.application.collection import CollectionContext
from honey_check.application.ports import (
    AppxQueryError,
    CancelToken,
    CimError,
    CimErrorKind,
    CimQuery,
    CimResult,
    CollectorPorts,
    FileMetadata,
    NativeDisplayMode,
    RegistryAccessDenied,
    RegistryHive,
    RegistryKeyMissing,
    RegistryView,
    SignatureResult,
    TpmNativeInfo,
)
from honey_check.domain.inventory import PathState


class FakeCim:
    """Responde por nombre de clase. Una clase sin datos devuelve lista vacía."""

    def __init__(
        self,
        rows: Mapping[str, list[dict[str, Any]]] | None = None,
        errors: Mapping[str, CimErrorKind] | None = None,
    ) -> None:
        self.rows = dict(rows or {})
        self.errors = dict(errors or {})
        self.calls: list[str] = []

    def query(
        self, queries: Sequence[CimQuery], cancel: CancelToken, timeout_s: float
    ) -> list[CimResult]:
        cancel.raise_if_cancelled()
        results = []
        for query in queries:
            self.calls.append(query.class_name)
            if query.class_name in self.errors:
                kind = self.errors[query.class_name]
                results.append(CimResult(error=CimError(kind, f"fallo simulado: {kind.value}")))
            else:
                results.append(CimResult(rows=tuple(self.rows.get(query.class_name, []))))
        return results


@dataclass
class FakeRegistry:
    """Claves como {(colmena, vista, ruta): valores}. Las subclaves se derivan de las rutas."""

    keys: dict[tuple[RegistryHive, RegistryView, str], dict[str, Any]] = field(default_factory=dict)
    denied: set[str] = field(default_factory=set)
    failing: set[str] = field(default_factory=set)
    last_write_value: datetime | None = None

    def put(
        self, hive: RegistryHive, view: RegistryView, path: str, values: dict[str, Any]
    ) -> None:
        self.keys[(hive, view, path)] = values

    def _check(self, path: str) -> None:
        if path in self.denied:
            raise RegistryAccessDenied(path)
        if path in self.failing:
            raise OSError("fallo simulado del Registro")

    def subkeys(self, hive: RegistryHive, path: str, view: RegistryView) -> list[str]:
        self._check(path)
        prefix = path + "\\"
        names = {
            key[2][len(prefix) :].split("\\")[0]
            for key in self.keys
            if key[0] == hive and key[1] == view and key[2].startswith(prefix)
        }
        if not names and (hive, view, path) not in self.keys:
            raise RegistryKeyMissing(path)
        return sorted(names)

    def values(self, hive: RegistryHive, path: str, view: RegistryView) -> dict[str, Any]:
        self._check(path)
        if (hive, view, path) not in self.keys:
            raise RegistryKeyMissing(path)
        return dict(self.keys[(hive, view, path)])

    def last_write(self, hive: RegistryHive, path: str, view: RegistryView) -> datetime | None:
        return self.last_write_value


@dataclass
class FakeFiles:
    existing: set[str] = field(default_factory=set)
    inaccessible: set[str] = field(default_factory=set)
    directories: dict[str, list[str]] = field(default_factory=dict)
    metadata_by_path: dict[str, FileMetadata] = field(default_factory=dict)
    texts: dict[str, str] = field(default_factory=dict)
    listed: list[str] = field(default_factory=list)

    def path_state(self, path: str) -> PathState:
        if path.startswith("\\\\"):
            return PathState.NOT_CHECKED
        if path in self.inaccessible:
            return PathState.INACCESSIBLE
        if path in self.existing or path in self.directories:
            return PathState.VALID
        return PathState.MISSING

    def list_executables(self, directory: str, limit: int) -> list[str]:
        self.listed.append(directory)
        return list(self.directories.get(directory, []))[:limit]

    def metadata(self, path: str) -> FileMetadata:
        return self.metadata_by_path.get(path, FileMetadata())

    def read_text(self, path: str, max_bytes: int) -> str | None:
        return self.texts.get(path)


@dataclass
class FakeSignatures:
    results: dict[str, SignatureResult] = field(default_factory=dict)
    received: list[str] = field(default_factory=list)

    def inspect(
        self, paths: Sequence[str], cancel: CancelToken, timeout_s: float
    ) -> dict[str, SignatureResult]:
        self.received.extend(paths)
        return {p: self.results[p] for p in paths if p in self.results}


@dataclass
class FakeNative:
    hostname: str | None = "PC-FICTICIO-01"
    firmware: str | None = "uefi"
    architecture: str | None = "x64"
    elevated: bool | None = False
    tpm: TpmNativeInfo | None = field(default_factory=lambda: TpmNativeInfo(True, "2.0"))
    modes: list[NativeDisplayMode] = field(
        default_factory=lambda: [NativeDisplayMode("Pantalla ficticia", True, 1920, 1080, 60)]
    )

    def computer_name(self) -> str | None:
        return self.hostname

    def firmware_mode(self) -> str | None:
        return self.firmware

    def native_architecture(self) -> str | None:
        return self.architecture

    def is_elevated(self) -> bool | None:
        return self.elevated

    def tpm_info(self) -> TpmNativeInfo | None:
        return self.tpm

    def display_modes(self) -> list[NativeDisplayMode]:
        return self.modes


@dataclass
class FakeAppx:
    rows: list[dict[str, Any]] = field(default_factory=list)
    error: CimErrorKind | None = None

    def packages(self, cancel: CancelToken, timeout_s: float) -> list[Mapping[str, Any]]:
        if self.error:
            raise AppxQueryError(self.error, "fallo simulado")
        return list(self.rows)


@dataclass
class FakePowerShellInfo:
    mode: str | None = "FullLanguage"

    def language_mode(self, cancel: CancelToken, timeout_s: float) -> str | None:
        return self.mode


def make_ports(
    cim: FakeCim | None = None,
    registry: FakeRegistry | None = None,
    files: FakeFiles | None = None,
    signatures: FakeSignatures | None = None,
    native: FakeNative | None = None,
    appx: FakeAppx | None = None,
    powershell: FakePowerShellInfo | None = None,
) -> CollectorPorts:
    return CollectorPorts(
        cim=cim or FakeCim(),
        registry=registry or FakeRegistry(),
        files=files or FakeFiles(),
        signatures=signatures or FakeSignatures(),
        native=native or FakeNative(),
        appx=appx or FakeAppx(),
        powershell=powershell or FakePowerShellInfo(),
    )


def make_context(ports: CollectorPorts, module: str = "prueba") -> CollectionContext:
    return CollectionContext(module=module, ports=ports, cancel=CancelToken(), timeout_s=30.0)


FIXED_TIME = datetime(2026, 11, 4, 15, 30, 0, tzinfo=UTC)

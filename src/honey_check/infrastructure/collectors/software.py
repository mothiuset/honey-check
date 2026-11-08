"""Inventario de software: vistas de desinstalación del Registro y paquetes AppX/MSIX.

Nunca usa `Win32_Product` (dispara reparaciones MSI) ni ejecuta nada de lo que lee: los comandos
de desinstalación se analizan como texto. La resolución de rutas es limitada: se inspeccionan
pocas carpetas con pocas entradas, nunca el disco completo.
"""

from __future__ import annotations

import hashlib
import ntpath
import re
import xml.etree.ElementTree as ET  # noqa: S405 - manifiestos locales, tamaño acotado, sin DTD
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from honey_check.application.collection import CollectionContext
from honey_check.application.ports import (
    AppxQueryError,
    CimErrorKind,
    RegistryAccessDenied,
    RegistryHive,
    RegistryKeyMissing,
    RegistryView,
)
from honey_check.domain.inventory import (
    DetectionMechanism,
    ExecutableDetails,
    ExecutableSignature,
    InstallerType,
    PathEvidence,
    PathState,
    SignatureStatus,
    SoftwareItem,
    SoftwareScope,
    SoftwareSection,
    SoftwareSourceReport,
    SoftwareSourceStatus,
    UninstallReference,
)
from honey_check.domain.normalize import clean_text, observed_positive_int, parse_yyyymmdd
from honey_check.domain.observed import Confidence, Observed, Reason

_UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
_APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
_MSI_USERDATA = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\UserData\S-1-5-18\Products"
_APPX_REPOSITORY = (
    r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
    r"\AppModel\Repository\Packages"
)

MAX_DIR_ENTRIES = 256
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
SIGNATURE_BUDGET_FRACTION = 0.4
RESOLVE_WORKERS = 8

_NOT_MAIN_EXECUTABLE = re.compile(
    r"(^|[-_ .])(unins\w*|uninstall\w*|setup\w*|install(er)?|update\w*|updater|crash\w*|"
    r"helper|repair|maintenance|elevat\w*|launcher_stub|autorun|vcredist\w*|dotnet\w*)"
    r"([-_ .\d]|$)",
    re.IGNORECASE,
)
# También sin separador, como en «OneDriveSetup» o «GoogleUpdate».
_NOT_MAIN_SUFFIX = re.compile(r"(setup|installer|install|uninstall|uninst|updater|update)$", re.I)
_SYSTEM_TOOLS = {
    "msiexec.exe",
    "rundll32.exe",
    "cmd.exe",
    "wscript.exe",
    "cscript.exe",
    "regsvr32.exe",
    "powershell.exe",
    "explorer.exe",
    "dllhost.exe",
}
_UNINSTALLER_DIRS = {"uninstall", "uninst", "_uninst", "uninstaller", "_uninstall", "uninstall_"}
_GENERIC_NAME_TOKENS = {
    "microsoft",
    "windows",
    "the",
    "for",
    "and",
    "app",
    "application",
    "software",
    "x64",
    "x86",
    "bit",
    "version",
    "edition",
    "update",
    "runtime",
    "redistributable",
    "pro",
}
_SEARCH_SUBDIRS = ("bin", "app", "program")
_GUID = re.compile(r"^\{[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$")
_APPX_ARCHITECTURES = {
    "x86": "x86",
    "x64": "x64",
    "arm": "arm",
    "arm64": "arm64",
    "neutral": "neutral",
}
_LIMITATIONS = [
    "Las aplicaciones portables sin registro de instalación no pueden detectarse.",
    "El software por usuario y los paquetes AppX solo se leen del usuario actual, salvo elevación.",
    "Las rutas de red no se comprueban para no bloquear el inventario.",
]


# --- Análisis de texto puro ----------------------------------------------------------------------


def parse_icon_path(raw: Any) -> str | None:
    """`DisplayIcon` tiene la forma `"C:\\ruta\\app.exe",0` o `C:\\ruta\\app.exe,0`."""
    text = clean_text(raw)
    if text is None:
        return None
    if text.startswith('"'):
        end = text.find('"', 1)
        return text[1:end].strip() or None if end > 0 else None
    return re.sub(r",\s*-?\d+\s*$", "", text).strip() or None


def parse_command_path(raw: Any) -> str | None:
    """Primer ejecutable de un comando, tratado solo como texto. Nunca se ejecuta."""
    text = clean_text(raw)
    if text is None:
        return None
    if text.startswith('"'):
        end = text.find('"', 1)
        return text[1:end].strip() or None if end > 0 else None
    match = re.match(r"^(.+?\.(?:exe|cmd|bat|com))(?=\s|$)", text, re.IGNORECASE)
    if match:
        return match.group(1)
    return text.split()[0] if " " not in text else None


def squished_msi_code(product_code: str) -> str | None:
    """Convierte un ProductCode en la forma comprimida de las claves de Windows Installer."""
    if not _GUID.match(product_code):
        return None
    groups = product_code.strip("{}").split("-")
    reversed_head = [group[::-1] for group in groups[:3]]
    swap = "".join(
        chunk[1] + chunk[0]
        for group in groups[3:]
        for chunk in (group[i : i + 2] for i in range(0, len(group), 2))
    )
    return ("".join(reversed_head) + swap).upper()


def architecture_from_name(name: str) -> str | None:
    lowered = name.lower()
    if re.search(r"\barm64\b", lowered):
        return "arm64"
    if re.search(r"(\bx64\b|\bamd64\b|\b64[- ]?bit\b|\bx86[-_]64\b)", lowered):
        return "x64"
    if re.search(r"(\bx86\b|\b32[- ]?bit\b)", lowered):
        return "x86"
    return None


def name_tokens(name: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", name.lower())
    return {w for w in words if len(w) >= 3 and w not in _GENERIC_NAME_TOKENS and not w.isdigit()}


def is_auxiliary_executable(path: str) -> bool:
    stem = ntpath.splitext(ntpath.basename(path))[0]
    return (
        bool(_NOT_MAIN_EXECUTABLE.search(stem))
        or bool(_NOT_MAIN_SUFFIX.search(stem))
        or ntpath.basename(path).lower() in _SYSTEM_TOOLS
    )


def _is_generated_or_system_location(path: str) -> bool:
    lowered = path.lower().replace("/", "\\")
    return (
        "\\windows\\installer\\" in lowered
        or "\\package cache\\" in lowered
        or "\\installshield installation information\\" in lowered
        or "\\windows\\system32\\" in lowered
        or "\\windows\\syswow64\\" in lowered
        or lowered.endswith("\\windows")
    )


def score_executable(path: str, tokens: set[str]) -> int:
    stem = ntpath.splitext(ntpath.basename(path))[0].lower()
    stem_tokens = set(re.findall(r"[a-z0-9]+", stem))
    if stem in tokens:
        return 3
    if stem_tokens & tokens:
        return 2
    if any(token in stem for token in tokens if len(token) >= 4):
        return 1
    if len(stem) >= 4 and any(stem in token for token in tokens):
        return 1
    return 0


def choose_candidate(candidates: Iterable[str], name: str) -> tuple[str, str] | None:
    """Elige el ejecutable más probable o ninguno. Un empate no se resuelve a ciegas."""
    usable = [c for c in candidates if not is_auxiliary_executable(c)]
    if not usable:
        return None
    tokens = name_tokens(name)
    scored = sorted(((score_executable(c, tokens), c) for c in usable), reverse=True)
    best_score = scored[0][0]
    if best_score > 0:
        best = [c for score, c in scored if score == best_score]
        if len(best) == 1:
            return best[0], "install_dir_name_match"
        return None
    if len(usable) == 1:
        return usable[0], "install_dir_single_executable"
    return None


def software_id(
    mechanism: DetectionMechanism, scope: SoftwareScope, view: str, key: str, name: str
) -> str:
    """Identidad estable entre inventarios del mismo equipo, independiente de la versión."""
    material = f"{mechanism.value}|{scope.value}|{view}|{key}|{name}".lower()
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


# --- Fuentes -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _RegistrySource:
    label: str
    hive: RegistryHive
    view: RegistryView
    scope: SoftwareScope
    implied_architecture: str | None


_REGISTRY_SOURCES = (
    _RegistrySource(
        "HKLM\\64", RegistryHive.LOCAL_MACHINE, RegistryView.BITS_64, SoftwareScope.MACHINE, "x64"
    ),
    _RegistrySource(
        "HKLM\\32", RegistryHive.LOCAL_MACHINE, RegistryView.BITS_32, SoftwareScope.MACHINE, "x86"
    ),
    _RegistrySource(
        "HKCU", RegistryHive.CURRENT_USER, RegistryView.DEFAULT, SoftwareScope.CURRENT_USER, None
    ),
)


class SoftwareCollector:
    name = "software"
    timeout_s = 240.0

    def collect(self, ctx: CollectionContext) -> SoftwareSection:
        reports: list[SoftwareSourceReport] = []
        items: list[SoftwareItem] = []
        skipped = 0

        app_paths = self._app_paths(ctx)
        for source in _REGISTRY_SOURCES:
            found, without_name, report = self._read_registry_source(ctx, source, app_paths)
            items.extend(found)
            skipped += without_name
            reports.append(report)

        appx_items, appx_report = self._read_appx(ctx)
        items.extend(appx_items)
        reports.append(appx_report)

        items = self._deduplicate(items)
        items, checked = self._verify_signatures(ctx, items)
        items.sort(key=lambda item: item.name.lower())

        if all(r.status not in (SoftwareSourceStatus.OK,) for r in reports):
            ctx.error("no_software_source", "Ninguna fuente de software respondió")
        return SoftwareSection(
            items=items,
            total_count=len(items),
            executable_resolved_count=sum(1 for i in items if i.executable_path.value),
            signature_checked_count=checked,
            skipped_entries_without_name=skipped,
            sources=reports,
            limitations=list(_LIMITATIONS),
        )

    # --- Registro --------------------------------------------------------------------------------

    def _read_registry_source(
        self, ctx: CollectionContext, source: _RegistrySource, app_paths: dict[str, str]
    ) -> tuple[list[SoftwareItem], int, SoftwareSourceReport]:
        registry = ctx.ports.registry
        label = f"registry:{source.label}"
        try:
            names = registry.subkeys(source.hive, _UNINSTALL, source.view)
        except RegistryKeyMissing:
            return (
                [],
                0,
                SoftwareSourceReport(
                    source=label, status=SoftwareSourceStatus.NOT_PRESENT, item_count=0
                ),
            )
        except RegistryAccessDenied:
            ctx.warn("access_denied", "Permisos insuficientes en la vista de desinstalación", label)
            return (
                [],
                0,
                SoftwareSourceReport(
                    source=label, status=SoftwareSourceStatus.ACCESS_DENIED, item_count=0
                ),
            )
        except OSError as error:
            ctx.error(
                "registry_error", f"No se pudo leer el Registro ({type(error).__name__})", label
            )
            return (
                [],
                0,
                SoftwareSourceReport(
                    source=label, status=SoftwareSourceStatus.FAILED, item_count=0
                ),
            )

        without_name = 0
        denied = 0
        pending: list[tuple[str, str, str, dict[str, Any]]] = []
        for name in names:
            ctx.cancel.raise_if_cancelled()
            path = f"{_UNINSTALL}\\{name}"
            try:
                values = registry.values(source.hive, path, source.view)
            except (RegistryKeyMissing, RegistryAccessDenied):
                denied += 1
                continue
            except OSError:
                denied += 1
                continue
            display_name = clean_text(values.get("DisplayName"))
            if display_name is None:
                without_name += 1
                continue
            pending.append((name, path, display_name, values))

        def resolve(entry: tuple[str, str, str, dict[str, Any]]) -> SoftwareItem:
            ctx.cancel.raise_if_cancelled()
            name, path, display_name, values = entry
            return self._registry_item(ctx, source, name, path, display_name, values, app_paths)

        # Resolver rutas y metadatos es sobre todo espera de disco: en paralelo, con tope.
        with ThreadPoolExecutor(RESOLVE_WORKERS, thread_name_prefix="software") as executor:
            items = list(executor.map(resolve, pending))
        detail = f"{denied} entradas no se pudieron leer" if denied else None
        if denied:
            ctx.warn(
                "unreadable_entries",
                f"{denied} entradas de desinstalación no se pudieron leer",
                label,
            )
        return (
            items,
            without_name,
            SoftwareSourceReport(
                source=label, status=SoftwareSourceStatus.OK, item_count=len(items), detail=detail
            ),
        )

    def _registry_item(
        self,
        ctx: CollectionContext,
        source: _RegistrySource,
        key: str,
        path: str,
        display_name: str,
        values: Mapping[str, Any],
        app_paths: dict[str, str],
    ) -> SoftwareItem:
        origin = f"registry:{source.label}\\{key}"
        files = ctx.ports.files
        is_msi = values.get("WindowsInstaller") == 1 or bool(_GUID.match(key))
        install_path = self._resolve_install_path(ctx, source, key, values, origin, is_msi)
        executable_path = self._resolve_executable(
            ctx, display_name, values, install_path, app_paths, origin
        )

        metadata = (
            files.metadata(executable_path.value)
            if executable_path.state is PathState.VALID and executable_path.value
            else None
        )
        details = None
        if metadata is not None:
            details = ExecutableDetails(
                file_version=metadata.file_version,
                product_version=metadata.product_version,
                product_name=metadata.product_name,
                file_description=metadata.file_description,
                company_name=metadata.company_name,
            )

        version: Observed[str]
        registry_version = clean_text(values.get("DisplayVersion"))
        if registry_version:
            version = Observed[str].reported(registry_version, f"{origin}.DisplayVersion")
        elif metadata is not None and (metadata.product_version or metadata.file_version):
            version = Observed[str].probable(
                str(metadata.product_version or metadata.file_version),
                "file_version_resource",
                "registry_has_no_display_version",
            )
        else:
            version = Observed[str].unknown(Reason.NOT_REPORTED, f"{origin}.DisplayVersion")

        publisher_raw = clean_text(values.get("Publisher"))
        publisher: Observed[str]
        if publisher_raw:
            publisher = Observed[str].reported(publisher_raw, f"{origin}.Publisher")
        elif metadata is not None and metadata.company_name:
            publisher = Observed[str].probable(
                metadata.company_name, "file_version_resource", "registry_has_no_publisher"
            )
        else:
            publisher = Observed[str].unknown(Reason.NOT_REPORTED, f"{origin}.Publisher")

        icon_id = self._icon(ctx, executable_path, values)
        return SoftwareItem(
            id=software_id(
                DetectionMechanism.REGISTRY_UNINSTALL, source.scope, source.label, key, display_name
            ),
            name=display_name,
            version=version,
            publisher=publisher,
            scope=source.scope,
            installer_type=self._installer_type(values, is_msi),
            mechanism=DetectionMechanism.REGISTRY_UNINSTALL,
            detection_source=origin,
            install_path=install_path,
            executable_path=executable_path,
            uninstall=self._uninstall_reference(ctx, values, origin),
            install_date=self._install_date(ctx, source, path, values, origin),
            architecture=self._architecture(
                source, display_name, executable_path, metadata.machine if metadata else None
            ),
            size_bytes=self._size(values, origin),
            executable=details,
            is_system_component=values.get("SystemComponent") == 1,
            icon_id=icon_id,
            is_update=bool(
                clean_text(values.get("ParentKeyName"))
                or values.get("ReleaseType") in ("Update", "Hotfix", "Security Update")
            ),
        )

    @staticmethod
    def _icon(
        ctx: CollectionContext, executable: PathEvidence, values: Mapping[str, Any]
    ) -> str | None:
        """Icono del ejecutable; si no hay, el de `DisplayIcon` aunque no sea el programa."""
        icons = ctx.ports.icons
        if icons is None:
            return None
        candidates = []
        if executable.value and executable.state is PathState.VALID:
            candidates.append(executable.value)
        icon = parse_icon_path(values.get("DisplayIcon"))
        if icon and icon.lower().endswith((".exe", ".ico", ".dll")) and ntpath.isabs(icon):
            candidates.append(icon)
        for candidate in candidates:
            if ctx.ports.files.path_state(candidate) is not PathState.VALID:
                continue
            data = icons.executable_icon(candidate)
            if data:
                return ctx.attach(data)
        return None

    @staticmethod
    def _installer_type(values: Mapping[str, Any], is_msi: bool) -> InstallerType:
        if is_msi:
            return InstallerType.MSI
        command = parse_command_path(values.get("UninstallString"))
        if command is None:
            return InstallerType.UNKNOWN
        if ntpath.basename(command).lower() in {"rundll32.exe", "cmd.exe"}:
            return InstallerType.OTHER
        return InstallerType.TRADITIONAL

    def _resolve_install_path(
        self,
        ctx: CollectionContext,
        source: _RegistrySource,
        key: str,
        values: Mapping[str, Any],
        origin: str,
        is_msi: bool,
    ) -> PathEvidence:
        files = ctx.ports.files
        location = clean_text(values.get("InstallLocation"))
        if location:
            location = location.strip('"').rstrip("\\/") or location
            return PathEvidence(
                value=location,
                confidence=Confidence.REPORTED,
                source=f"{origin}.InstallLocation",
                state=files.path_state(location),
            )

        inno = clean_text(values.get("Inno Setup: App Path"))
        if inno:
            inno = inno.rstrip("\\/")
            return PathEvidence(
                value=inno,
                confidence=Confidence.REPORTED,
                source=f"{origin}.Inno Setup: App Path",
                state=files.path_state(inno),
            )

        if is_msi and source.hive is RegistryHive.LOCAL_MACHINE:
            msi_location = self._msi_install_location(ctx, key)
            if msi_location:
                msi_location = msi_location.rstrip("\\/")
                return PathEvidence(
                    value=msi_location,
                    confidence=Confidence.REPORTED,
                    source="registry:WindowsInstaller.InstallProperties.InstallLocation",
                    state=files.path_state(msi_location),
                )

        for raw, label in (
            (parse_icon_path(values.get("DisplayIcon")), "display_icon_parent"),
            (parse_command_path(values.get("UninstallString")), "uninstaller_parent"),
        ):
            parent = self._derived_parent(raw)
            if parent:
                state = files.path_state(parent)
                if state is PathState.VALID:
                    return PathEvidence(
                        value=parent,
                        confidence=Confidence.PROBABLE,
                        source=f"rule:{label}",
                        state=state,
                        reason="derived_install_location",
                    )
        return PathEvidence(reason="install_location_not_reported")

    @staticmethod
    def _derived_parent(raw: str | None) -> str | None:
        if raw is None or not ntpath.isabs(raw):
            return None
        if ntpath.basename(raw).lower() in _SYSTEM_TOOLS or _is_generated_or_system_location(raw):
            return None
        parent = ntpath.dirname(raw)
        if ntpath.basename(parent).lower() in _UNINSTALLER_DIRS:
            parent = ntpath.dirname(parent)
        if not parent or parent.rstrip("\\/").endswith(":"):
            return None
        return parent if not _is_generated_or_system_location(parent) else None

    @staticmethod
    def _msi_install_location(ctx: CollectionContext, product_code: str) -> str | None:
        squished = squished_msi_code(product_code)
        if squished is None:
            return None
        try:
            values = ctx.ports.registry.values(
                RegistryHive.LOCAL_MACHINE,
                f"{_MSI_USERDATA}\\{squished}\\InstallProperties",
                RegistryView.BITS_64,
            )
        except (RegistryKeyMissing, RegistryAccessDenied, OSError):
            return None
        return clean_text(values.get("InstallLocation"))

    def _resolve_executable(
        self,
        ctx: CollectionContext,
        display_name: str,
        values: Mapping[str, Any],
        install_path: PathEvidence,
        app_paths: dict[str, str],
        origin: str,
    ) -> PathEvidence:
        files = ctx.ports.files

        icon = parse_icon_path(values.get("DisplayIcon"))
        rejected_icon = False
        if icon:
            if (
                icon.lower().endswith(".exe")
                and ntpath.isabs(icon)
                and not is_auxiliary_executable(icon)
                and not _is_generated_or_system_location(icon)
            ):
                state = files.path_state(icon)
                if state is PathState.VALID:
                    return PathEvidence(
                        value=icon,
                        confidence=Confidence.REPORTED,
                        source=f"{origin}.DisplayIcon",
                        state=state,
                    )
                rejected_icon = True
            else:
                rejected_icon = True

        if install_path.value and install_path.state is PathState.VALID:
            base = install_path.value.lower().rstrip("\\/") + "\\"
            inside = [p for p in app_paths.values() if p.lower().startswith(base)]
            match = choose_candidate(inside, display_name)
            if match and files.path_state(match[0]) is PathState.VALID:
                return PathEvidence(
                    value=match[0],
                    confidence=Confidence.REPORTED,
                    source="registry:App Paths",
                    state=PathState.VALID,
                )

            candidates = files.list_executables(install_path.value, MAX_DIR_ENTRIES)
            match = choose_candidate(candidates, display_name)
            if match is None:
                for subdir in _SEARCH_SUBDIRS:
                    match = choose_candidate(
                        files.list_executables(
                            ntpath.join(install_path.value, subdir), MAX_DIR_ENTRIES
                        ),
                        display_name,
                    )
                    if match:
                        break
            if match:
                return PathEvidence(
                    value=match[0],
                    confidence=Confidence.PROBABLE,
                    source=f"rule:{match[1]}",
                    state=PathState.VALID,
                    reason="heuristic_candidate",
                )
            return PathEvidence(reason="no_unambiguous_executable_in_install_path")

        tokens = name_tokens(display_name)
        by_name = [
            path
            for exe, path in app_paths.items()
            if ntpath.splitext(exe)[0].lower() in tokens and not is_auxiliary_executable(path)
        ]
        if len(by_name) == 1 and files.path_state(by_name[0]) is PathState.VALID:
            return PathEvidence(
                value=by_name[0],
                confidence=Confidence.PROBABLE,
                source="rule:app_paths_name_match",
                state=PathState.VALID,
                reason="heuristic_candidate",
            )
        if install_path.value and install_path.state is PathState.MISSING:
            return PathEvidence(reason="install_path_missing_on_disk")
        if install_path.value and install_path.state is PathState.INACCESSIBLE:
            return PathEvidence(reason="install_path_inaccessible")
        if rejected_icon:
            return PathEvidence(reason="display_icon_is_not_the_main_executable")
        return PathEvidence(reason="windows_does_not_identify_executable")

    @staticmethod
    def _uninstall_reference(
        ctx: CollectionContext, values: Mapping[str, Any], origin: str
    ) -> UninstallReference | None:
        command = clean_text(values.get("UninstallString"))
        if command is None:
            return None
        parsed = parse_command_path(command)
        if parsed is None or not ntpath.isabs(parsed):
            path = PathEvidence(reason="command_without_absolute_path")
        else:
            path = PathEvidence(
                value=parsed,
                confidence=Confidence.REPORTED,
                source=f"{origin}.UninstallString",
                state=ctx.ports.files.path_state(parsed),
            )
        return UninstallReference(command=command, path=path)

    @staticmethod
    def _install_date(
        ctx: CollectionContext,
        source: _RegistrySource,
        path: str,
        values: Mapping[str, Any],
        origin: str,
    ) -> Observed[str]:
        raw = clean_text(values.get("InstallDate"))
        parsed = parse_yyyymmdd(raw)
        if parsed:
            return Observed[str].reported(parsed, f"{origin}.InstallDate")
        try:
            moment = ctx.ports.registry.last_write(source.hive, path, source.view)
        except (RegistryKeyMissing, RegistryAccessDenied, OSError):
            moment = None
        if moment is not None:
            return Observed[str].probable(
                moment.date().isoformat(),
                f"{origin}.lastWriteTime",
                "last_registry_modification_not_install_date",
            )
        reason = Reason.INVALID_VALUE if raw else Reason.NOT_REPORTED
        return Observed[str].unknown(reason, f"{origin}.InstallDate", raw=raw)

    @staticmethod
    def _architecture(
        source: _RegistrySource, name: str, executable: PathEvidence, machine: str | None
    ) -> Observed[str]:
        """Solo la cabecera PE verifica la arquitectura.

        La vista del Registro refleja al instalador, no al producto: muchos instaladores de
        32 bits registran productos x64 en WOW6432Node. Por eso es la pista más débil.
        """
        if machine:
            if executable.confidence is Confidence.PROBABLE:
                return Observed[str].probable(machine, "pe_header", "executable_is_a_candidate")
            return Observed[str].verified(machine, "pe_header")
        from_name = architecture_from_name(name)
        if from_name:
            return Observed[str].probable(from_name, "rule:display_name", "declared_in_name")
        if source.implied_architecture:
            return Observed[str].probable(
                source.implied_architecture,
                f"rule:registry_view_{source.label}",
                "registry_view_reflects_the_installer",
            )
        return Observed[str].unknown(Reason.NOT_RESOLVED, "pe_header")

    @staticmethod
    def _size(values: Mapping[str, Any], origin: str) -> Observed[int]:
        kib = observed_positive_int(values.get("EstimatedSize"), f"{origin}.EstimatedSize")
        if kib.value is None:
            return kib
        return Observed[int].reported(kib.value * 1024, f"{origin}.EstimatedSize")

    @staticmethod
    def _app_paths(ctx: CollectionContext) -> dict[str, str]:
        """Mapa nombre de ejecutable → ruta, de las vistas de máquina y del usuario."""
        found: dict[str, str] = {}
        registry = ctx.ports.registry
        for hive, view in (
            (RegistryHive.LOCAL_MACHINE, RegistryView.BITS_64),
            (RegistryHive.LOCAL_MACHINE, RegistryView.BITS_32),
            (RegistryHive.CURRENT_USER, RegistryView.DEFAULT),
        ):
            try:
                names = registry.subkeys(hive, _APP_PATHS, view)
            except (RegistryKeyMissing, RegistryAccessDenied, OSError):
                continue
            for name in names:
                try:
                    values = registry.values(hive, f"{_APP_PATHS}\\{name}", view)
                except (RegistryKeyMissing, RegistryAccessDenied, OSError):
                    continue
                path = clean_text(values.get(""))
                if path:
                    found.setdefault(name.lower(), path.strip('"'))
        return found

    # --- AppX/MSIX -------------------------------------------------------------------------------

    def _read_appx(self, ctx: CollectionContext) -> tuple[list[SoftwareItem], SoftwareSourceReport]:
        label = "appx:Get-AppxPackage"
        try:
            packages = ctx.ports.appx.packages(ctx.cancel, min(60.0, ctx.timeout_s / 3))
        except AppxQueryError as error:
            items = self._read_appx_repository(ctx)
            status = (
                SoftwareSourceStatus.ACCESS_DENIED
                if error.kind is CimErrorKind.ACCESS_DENIED
                else SoftwareSourceStatus.FAILED
            )
            ctx.warn(
                "appx_query_failed",
                f"Get-AppxPackage no respondió; se leyó el Registro: {error}",
                label,
            )
            return items, SoftwareSourceReport(
                source=label,
                status=status,
                item_count=len(items),
                detail="se usó la lista del Registro del usuario actual",
            )
        items = [
            self._appx_item(ctx, package)
            for package in packages
            if not package.get("IsResourcePackage")
        ]
        return items, SoftwareSourceReport(
            source=label, status=SoftwareSourceStatus.OK, item_count=len(items)
        )

    def _appx_item(self, ctx: CollectionContext, package: Mapping[str, Any]) -> SoftwareItem:
        files = ctx.ports.files
        origin = "appx:Get-AppxPackage"
        package_name = clean_text(package.get("Name")) or "paquete-sin-nombre"
        full_name = clean_text(package.get("PackageFullName")) or package_name
        location = clean_text(package.get("InstallLocation"))

        install_path = (
            PathEvidence(
                value=location,
                confidence=Confidence.REPORTED,
                source=f"{origin}.InstallLocation",
                state=files.path_state(location),
            )
            if location
            else PathEvidence(reason="package_without_install_location")
        )
        manifest = self._read_manifest(ctx, location) if location else None

        display_name = manifest.display_name if manifest and manifest.display_name else package_name
        executable = self._manifest_executable(ctx, location, manifest)
        metadata = (
            files.metadata(executable.value)
            if executable.state is PathState.VALID and executable.value
            else None
        )
        details = (
            ExecutableDetails(
                file_version=metadata.file_version,
                product_version=metadata.product_version,
                product_name=metadata.product_name,
                file_description=metadata.file_description,
                company_name=metadata.company_name,
                signature=ExecutableSignature(
                    status=SignatureStatus.NOT_CHECKED,
                    reason="package_signature_reported_instead",
                ),
            )
            if metadata
            else None
        )

        architecture_raw = (clean_text(package.get("Architecture")) or "").lower()
        architecture = _APPX_ARCHITECTURES.get(architecture_raw)
        publisher = (
            Observed[str].reported(manifest.publisher, f"{origin}.manifest.PublisherDisplayName")
            if manifest and manifest.publisher
            else self._publisher_from_subject(package.get("Publisher"), origin)
        )
        version_text = clean_text(package.get("Version"))
        icon_id = None
        if ctx.ports.icons is not None and location and manifest and manifest.logo:
            logo = ctx.ports.icons.package_logo(location, manifest.logo)
            icon_id = ctx.attach(logo) if logo else None
        return SoftwareItem(
            id=software_id(
                DetectionMechanism.APPX_PACKAGE,
                SoftwareScope.CURRENT_USER,
                "appx",
                package_name,
                "",
            ),
            name=display_name,
            version=(
                Observed[str].reported(version_text, f"{origin}.Version")
                if version_text
                else Observed[str].unknown(Reason.NOT_REPORTED, f"{origin}.Version")
            ),
            publisher=publisher,
            scope=SoftwareScope.CURRENT_USER,
            installer_type=InstallerType.MSIX,
            mechanism=DetectionMechanism.APPX_PACKAGE,
            detection_source=origin,
            install_path=install_path,
            executable_path=executable,
            uninstall=None,
            install_date=Observed[str].unknown(Reason.NOT_AVAILABLE, origin),
            architecture=(
                Observed[str].reported(architecture, f"{origin}.Architecture")
                if architecture
                else Observed[str].unknown(Reason.NOT_REPORTED, f"{origin}.Architecture")
            ),
            size_bytes=Observed[int].unknown(Reason.NOT_AVAILABLE, origin),
            executable=details,
            package_full_name=full_name,
            package_signature_kind=clean_text(package.get("SignatureKind")),
            is_system_component=bool(package.get("NonRemovable")),
            is_framework=bool(package.get("IsFramework")),
            icon_id=icon_id,
        )

    @staticmethod
    def _publisher_from_subject(raw: Any, origin: str) -> Observed[str]:
        text = clean_text(raw)
        if text is None:
            return Observed[str].unknown(Reason.NOT_REPORTED, f"{origin}.Publisher")
        match = re.search(r"(?:^|,\s*)(?:CN|O)=([^,]+)", text)
        return Observed[str].reported(
            match.group(1).strip() if match else text, f"{origin}.Publisher"
        )

    def _read_manifest(self, ctx: CollectionContext, location: str) -> _Manifest | None:
        text = ctx.ports.files.read_text(
            ntpath.join(location, "AppxManifest.xml"), MAX_MANIFEST_BYTES
        )
        return parse_appx_manifest(text) if text else None

    @staticmethod
    def _manifest_executable(
        ctx: CollectionContext, location: str | None, manifest: _Manifest | None
    ) -> PathEvidence:
        if not location:
            return PathEvidence(reason="package_without_install_location")
        if manifest is None:
            return PathEvidence(reason="package_manifest_not_readable")
        if not manifest.executable:
            return PathEvidence(reason="package_declares_no_executable")
        path = ntpath.normpath(ntpath.join(location, manifest.executable))
        return PathEvidence(
            value=path,
            confidence=Confidence.REPORTED,
            source="appx:manifest.Application.Executable",
            state=ctx.ports.files.path_state(path),
        )

    def _read_appx_repository(self, ctx: CollectionContext) -> list[SoftwareItem]:
        """Alternativa sin PowerShell: índice de paquetes del usuario actual en el Registro."""
        registry = ctx.ports.registry
        try:
            names = registry.subkeys(
                RegistryHive.CURRENT_USER, _APPX_REPOSITORY, RegistryView.DEFAULT
            )
        except (RegistryKeyMissing, RegistryAccessDenied, OSError):
            return []
        packages: list[dict[str, Any]] = []
        for name in names:
            parts = name.split("_")
            if len(parts) < 5:
                continue
            try:
                values = registry.values(
                    RegistryHive.CURRENT_USER, f"{_APPX_REPOSITORY}\\{name}", RegistryView.DEFAULT
                )
            except (RegistryKeyMissing, RegistryAccessDenied, OSError):
                continue
            packages.append(
                {
                    "Name": parts[0],
                    "Version": parts[1],
                    "Architecture": parts[2],
                    "PackageFullName": name,
                    "InstallLocation": values.get("PackageRootFolder"),
                    "IsResourcePackage": parts[3] not in ("", "~")
                    and "resource" in parts[3].lower(),
                }
            )
        return [self._appx_item(ctx, p) for p in packages if not p.get("IsResourcePackage")]

    # --- Revisión final --------------------------------------------------------------------------

    @staticmethod
    def _deduplicate(items: list[SoftwareItem]) -> list[SoftwareItem]:
        """Solo fusiona entradas idénticas; dos arquitecturas de un programa siguen separadas."""
        seen: dict[tuple[Any, ...], SoftwareItem] = {}
        for item in items:
            key = (
                item.name.lower(),
                item.version.value,
                item.scope,
                item.mechanism,
                item.architecture.value,
                (item.install_path.value or "").lower(),
            )
            seen.setdefault(key, item)
        return list(seen.values())

    @staticmethod
    def _verify_signatures(
        ctx: CollectionContext, items: list[SoftwareItem]
    ) -> tuple[list[SoftwareItem], int]:
        paths = sorted(
            {
                item.executable_path.value
                for item in items
                if item.executable_path.value
                and item.executable_path.state is PathState.VALID
                and item.mechanism is DetectionMechanism.REGISTRY_UNINSTALL
            }
        )
        if not paths:
            return items, 0
        budget = ctx.timeout_s * SIGNATURE_BUDGET_FRACTION
        found = ctx.ports.signatures.inspect(paths, ctx.cancel, budget)
        if len(found) < len(paths):
            ctx.warn(
                "signatures_incomplete",
                f"Se verificaron {len(found)} de {len(paths)} firmas dentro del tiempo disponible",
                "powershell:Get-AuthenticodeSignature",
            )
        updated: list[SoftwareItem] = []
        for item in items:
            path = item.executable_path.value
            result = found.get(path) if path else None
            if result is not None and item.executable is not None:
                signature = ExecutableSignature(
                    status=SignatureStatus(result.status), signer=result.signer
                )
                executable = item.executable.model_copy(update={"signature": signature})
                updated.append(item.model_copy(update={"executable": executable}))
            elif (
                item.executable is not None
                and path
                and item.mechanism is DetectionMechanism.REGISTRY_UNINSTALL
            ):
                signature = ExecutableSignature(
                    status=SignatureStatus.NOT_CHECKED, reason="time_budget_exhausted"
                )
                executable = item.executable.model_copy(update={"signature": signature})
                updated.append(item.model_copy(update={"executable": executable}))
            else:
                updated.append(item)
        return updated, len(found)


@dataclass(frozen=True)
class _Manifest:
    display_name: str | None
    publisher: str | None
    executable: str | None
    logo: str | None = None


def parse_appx_manifest(text: str) -> _Manifest | None:
    """Rechaza DTD/entidades: un manifiesto de paquete legítimo no las necesita."""
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        return None
    try:
        root = ET.fromstring(text)  # noqa: S314 - ya sin DTD ni entidades
    except ET.ParseError:
        return None

    def local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    display_name: str | None = None
    publisher: str | None = None
    executable: str | None = None
    logo: str | None = None
    for element in root.iter():
        name = local(element.tag)
        if name == "DisplayName" and display_name is None:
            value = clean_text(element.text)
            if value and not value.lower().startswith("ms-resource:"):
                display_name = value
        elif name == "PublisherDisplayName" and publisher is None:
            value = clean_text(element.text)
            if value and not value.lower().startswith("ms-resource:"):
                publisher = value
        elif name == "Logo" and logo is None:
            value = clean_text(element.text)
            if value and value.lower().endswith(".png") and ".." not in value:
                logo = value
        elif name == "Application" and executable is None:
            exe = clean_text(element.get("Executable"))
            if exe and exe.lower().endswith(".exe") and ".." not in exe and not ntpath.isabs(exe):
                executable = exe
    return _Manifest(display_name, publisher, executable, logo)


__all__ = [
    "SoftwareCollector",
    "architecture_from_name",
    "choose_candidate",
    "name_tokens",
    "parse_appx_manifest",
    "parse_command_path",
    "parse_icon_path",
    "score_executable",
    "software_id",
    "squished_msi_code",
]

"""Inventario de software con Registro y archivos simulados (mocks)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from fakes import FakeAppx, FakeFiles, FakeRegistry, FakeSignatures, make_context, make_ports
from honey_check.application.ports import (
    CimErrorKind,
    FileMetadata,
    RegistryHive,
    RegistryView,
    SignatureResult,
)
from honey_check.domain.inventory import (
    DetectionMechanism,
    InstallerType,
    PathState,
    SignatureStatus,
    SoftwareScope,
    SoftwareSourceStatus,
)
from honey_check.domain.observed import Confidence
from honey_check.infrastructure.collectors.software import (
    SoftwareCollector,
    architecture_from_name,
    choose_candidate,
    is_auxiliary_executable,
    parse_appx_manifest,
    parse_command_path,
    parse_icon_path,
    software_id,
    squished_msi_code,
)

UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
HKLM = RegistryHive.LOCAL_MACHINE
HKCU = RegistryHive.CURRENT_USER
V64 = RegistryView.BITS_64
V32 = RegistryView.BITS_32
DEFAULT = RegistryView.DEFAULT


def collect(
    registry: FakeRegistry | None = None,
    files: FakeFiles | None = None,
    appx: FakeAppx | None = None,
    signatures: FakeSignatures | None = None,
) -> tuple[Any, Any]:
    ctx = make_context(
        make_ports(registry=registry, files=files, appx=appx, signatures=signatures), "software"
    )
    return SoftwareCollector().collect(ctx), ctx


def registry_with(*entries: tuple[RegistryHive, RegistryView, str, dict[str, Any]]) -> FakeRegistry:
    registry = FakeRegistry()
    for hive, view, key, values in entries:
        registry.put(hive, view, f"{UNINSTALL}\\{key}", values)
    return registry


def only(section: Any, name: str) -> Any:
    found = [item for item in section.items if item.name == name]
    assert len(found) == 1, [item.name for item in section.items]
    return found[0]


class TestParsers:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ('"C:\\App\\a.exe",0', "C:\\App\\a.exe"),
            ("C:\\App\\a.exe,0", "C:\\App\\a.exe"),
            ("C:\\App Dir\\a.exe, -101", "C:\\App Dir\\a.exe"),
            ("C:\\App\\icon.ico", "C:\\App\\icon.ico"),
            ("", None),
            (None, None),
            ('"sin-cierre', None),
        ],
    )
    def test_icon(self, raw: Any, expected: str | None) -> None:
        assert parse_icon_path(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ('"C:\\Program Files\\App\\unins000.exe" /S', "C:\\Program Files\\App\\unins000.exe"),
            ("C:\\Program Files\\App\\uninstall.exe /S", "C:\\Program Files\\App\\uninstall.exe"),
            ("MsiExec.exe /X{AAAAAAAA-0000-0000-0000-000000000000}", "MsiExec.exe"),
            ("rundll32.exe dfshim.dll,ShArpMaintain a", "rundll32.exe"),
            (None, None),
        ],
    )
    def test_command_is_parsed_as_text(self, raw: Any, expected: str | None) -> None:
        assert parse_command_path(raw) == expected

    def test_msi_squished_code_exact(self) -> None:
        # Regla de Windows Installer: los tres primeros grupos se invierten; el resto por pares.
        assert squished_msi_code("{12345678-90AB-CDEF-1234-567890ABCDEF}") == (
            "87654321BA09FEDC2143658709BADCFE"
        )
        assert squished_msi_code("no-es-guid") is None

    @pytest.mark.parametrize(
        "path",
        [
            "C:\\A\\unins000.exe",
            "C:\\A\\uninstall.exe",
            "C:\\A\\setup.exe",
            "C:\\A\\OneDriveSetup.exe",
            "C:\\A\\GoogleUpdate.exe",
            "C:\\A\\crashpad_handler.exe",
            "C:\\A\\msiexec.exe",
        ],
    )
    def test_auxiliary_executables(self, path: str) -> None:
        assert is_auxiliary_executable(path)

    @pytest.mark.parametrize(
        "path", ["C:\\A\\app.exe", "C:\\A\\Editor.exe", "C:\\A\\installed.exe"]
    )
    def test_regular_executables(self, path: str) -> None:
        assert not is_auxiliary_executable(path)

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Herramienta 1.0 (x64)", "x64"),
            ("Herramienta (64-bit)", "x64"),
            ("Herramienta amd64", "x64"),
            ("Herramienta x86", "x86"),
            ("Herramienta 32 bit", "x86"),
            ("Herramienta ARM64", "arm64"),
            ("Herramienta", None),
        ],
    )
    def test_architecture_from_name(self, name: str, expected: str | None) -> None:
        assert architecture_from_name(name) == expected

    def test_candidate_by_name(self) -> None:
        assert choose_candidate(["C:\\A\\helper.exe", "C:\\A\\editor.exe"], "Editor Ficticio") == (
            "C:\\A\\editor.exe",
            "install_dir_name_match",
        )

    def test_single_candidate(self) -> None:
        assert choose_candidate(["C:\\A\\zzz.exe", "C:\\A\\unins000.exe"], "Otro Nombre") == (
            "C:\\A\\zzz.exe",
            "install_dir_single_executable",
        )

    def test_ambiguous_candidates_are_not_guessed(self) -> None:
        assert choose_candidate(["C:\\A\\uno.exe", "C:\\A\\dos.exe"], "Otro Nombre") is None

    def test_tied_candidates_are_not_guessed(self) -> None:
        assert choose_candidate(["C:\\A\\tool-a.exe", "C:\\A\\tool-b.exe"], "Tool") is None

    def test_stable_id_ignores_version(self) -> None:
        make = lambda: software_id(  # noqa: E731
            DetectionMechanism.REGISTRY_UNINSTALL, SoftwareScope.MACHINE, "HKLM\\64", "App", "App"
        )
        assert make() == make()


class TestManifest:
    MANIFEST = """<?xml version="1.0"?>
    <Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">
      <Properties>
        <DisplayName>App Ficticia</DisplayName>
        <PublisherDisplayName>Editor Ficticio</PublisherDisplayName>
      </Properties>
      <Applications><Application Id="App" Executable="bin\\app.exe"/></Applications>
    </Package>"""

    def test_parses(self) -> None:
        manifest = parse_appx_manifest(self.MANIFEST)
        assert manifest is not None
        assert manifest.display_name == "App Ficticia"
        assert manifest.publisher == "Editor Ficticio"
        assert manifest.executable == "bin\\app.exe"

    def test_rejects_entities(self) -> None:
        evil = '<!DOCTYPE a [<!ENTITY x "y">]><Package><DisplayName>&x;</DisplayName></Package>'
        assert parse_appx_manifest(evil) is None

    def test_rejects_invalid_xml(self) -> None:
        assert parse_appx_manifest("<Package>") is None

    def test_resource_names_are_ignored(self) -> None:
        manifest = parse_appx_manifest(
            "<Package><DisplayName>ms-resource:AppName</DisplayName></Package>"
        )
        assert manifest is not None
        assert manifest.display_name is None

    def test_path_traversal_in_executable_is_rejected(self) -> None:
        manifest = parse_appx_manifest(
            '<Package><Application Executable="..\\..\\Windows\\cmd.exe"/></Package>'
        )
        assert manifest is not None
        assert manifest.executable is None


class TestRegistrySoftware:
    def test_x64_app_with_verified_architecture(self) -> None:
        exe = "C:\\Program Files\\Editor\\editor.exe"
        registry = registry_with(
            (
                HKLM,
                V64,
                "Editor",
                {
                    "DisplayName": "Editor Ficticio",
                    "DisplayVersion": "1.2.3",
                    "Publisher": "Editorial Ficticia",
                    "InstallLocation": "C:\\Program Files\\Editor\\",
                    "DisplayIcon": f'"{exe}",0',
                    "UninstallString": '"C:\\Program Files\\Editor\\unins000.exe" /S',
                    "InstallDate": "20260115",
                    "EstimatedSize": 2048,
                },
            )
        )
        files = FakeFiles(
            existing={exe, "C:\\Program Files\\Editor\\unins000.exe"},
            directories={"C:\\Program Files\\Editor": []},
            metadata_by_path={
                exe: FileMetadata(
                    file_version="1.2.3.4",
                    product_version="1.2.3",
                    product_name="Editor",
                    company_name="Editorial Ficticia",
                    machine="x64",
                )
            },
        )
        signatures = FakeSignatures({exe: SignatureResult("valid", "CN=Editorial Ficticia")})
        section, ctx = collect(registry, files, signatures=signatures)
        item = only(section, "Editor Ficticio")
        assert item.version.value == "1.2.3"
        assert item.publisher.value == "Editorial Ficticia"
        assert item.scope is SoftwareScope.MACHINE
        assert item.installer_type is InstallerType.TRADITIONAL
        # La carpeta y el ejecutable son cosas distintas.
        assert item.install_path.value == "C:\\Program Files\\Editor"
        assert item.install_path.state is PathState.VALID
        assert item.executable_path.value == exe
        assert item.executable_path.confidence is Confidence.REPORTED
        assert item.architecture.value == "x64"
        assert item.architecture.confidence is Confidence.VERIFIED
        assert item.install_date.value == "2026-01-15"
        assert item.size_bytes.value == 2048 * 1024
        assert item.executable.file_version == "1.2.3.4"
        assert item.executable.signature.status is SignatureStatus.VALID
        assert item.executable.signature.signer == "CN=Editorial Ficticia"
        assert item.uninstall.command.endswith("/S")
        assert item.uninstall.path.state is PathState.VALID
        assert section.signature_checked_count == 1
        assert ctx.errors == []

    def test_x86_app_in_32bit_view(self) -> None:
        exe = "C:\\Program Files (x86)\\Vieja\\vieja.exe"
        registry = registry_with(
            (HKLM, V32, "Vieja", {"DisplayName": "App Vieja", "DisplayIcon": exe})
        )
        files = FakeFiles(existing={exe}, metadata_by_path={exe: FileMetadata(machine="x86")})
        item = only(collect(registry, files)[0], "App Vieja")
        assert item.architecture.value == "x86"
        assert item.architecture.confidence is Confidence.VERIFIED

    def test_x64_product_registered_by_32bit_installer_is_not_called_x86(self) -> None:
        """Regresión: un producto «(x64)» en WOW6432Node no es x86."""
        registry = registry_with((HKLM, V32, "Sdk", {"DisplayName": "SDK Ficticio 10 (x64)"}))
        item = only(collect(registry)[0], "SDK Ficticio 10 (x64)")
        assert item.architecture.value == "x64"
        assert item.architecture.confidence is Confidence.PROBABLE

    def test_registry_view_alone_is_only_probable(self) -> None:
        registry = registry_with((HKLM, V32, "Lib", {"DisplayName": "Biblioteca Ficticia"}))
        item = only(collect(registry)[0], "Biblioteca Ficticia")
        assert item.architecture.value == "x86"
        assert item.architecture.confidence is Confidence.PROBABLE
        assert item.architecture.reason == "registry_view_reflects_the_installer"

    def test_both_architectures_stay_separate(self) -> None:
        registry = registry_with(
            (HKLM, V64, "Rt", {"DisplayName": "Runtime Ficticio", "DisplayVersion": "1"}),
            (HKLM, V32, "Rt", {"DisplayName": "Runtime Ficticio", "DisplayVersion": "1"}),
        )
        section, _ = collect(registry)
        assert section.total_count == 2

    def test_identical_duplicates_are_merged(self) -> None:
        registry = registry_with(
            (HKLM, V64, "A1", {"DisplayName": "Duplicado", "DisplayVersion": "1"}),
            (HKLM, V64, "A2", {"DisplayName": "Duplicado", "DisplayVersion": "1"}),
        )
        assert collect(registry)[0].total_count == 1

    def test_without_install_location_uses_uninstaller_parent_as_probable(self) -> None:
        directory = "C:\\Apps\\Sinruta"
        registry = registry_with(
            (
                HKLM,
                V64,
                "Sinruta",
                {"DisplayName": "Sinruta", "UninstallString": f'"{directory}\\uninstall.exe" /S'},
            )
        )
        files = FakeFiles(
            existing={f"{directory}\\uninstall.exe"},
            directories={directory: [f"{directory}\\sinruta.exe", f"{directory}\\uninstall.exe"]},
        )
        item = only(collect(registry, files)[0], "Sinruta")
        assert item.install_path.value == directory
        assert item.install_path.confidence is Confidence.PROBABLE
        assert item.install_path.source == "rule:uninstaller_parent"
        assert item.executable_path.value == f"{directory}\\sinruta.exe"
        assert item.executable_path.confidence is Confidence.PROBABLE

    def test_uninstaller_subfolder_points_to_real_folder(self) -> None:
        registry = registry_with(
            (
                HKLM,
                V64,
                "Sub",
                {"DisplayName": "Sub", "UninstallString": '"C:\\Apps\\Sub\\uninst\\u.exe"'},
            )
        )
        files = FakeFiles(
            directories={"C:\\Apps\\Sub": []}, existing={"C:\\Apps\\Sub\\uninst\\u.exe"}
        )
        item = only(collect(registry, files)[0], "Sub")
        assert item.install_path.value == "C:\\Apps\\Sub"

    def test_msi_location_comes_from_installer_data(self) -> None:
        code = "{12345678-90AB-CDEF-1234-567890ABCDEF}"
        registry = registry_with(
            (
                HKLM,
                V64,
                code,
                {
                    "DisplayName": "Producto MSI",
                    "WindowsInstaller": 1,
                    "UninstallString": f"MsiExec.exe /X{code}",
                },
            )
        )
        registry.put(
            HKLM,
            V64,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Installer\UserData\S-1-5-18\Products"
            r"\87654321BA09FEDC2143658709BADCFE\InstallProperties",
            {"InstallLocation": "C:\\Apps\\Msi\\"},
        )
        files = FakeFiles(directories={"C:\\Apps\\Msi": []})
        item = only(collect(registry, files)[0], "Producto MSI")
        assert item.installer_type is InstallerType.MSI
        assert item.install_path.value == "C:\\Apps\\Msi"
        assert item.install_path.source.startswith("registry:WindowsInstaller")
        # MsiExec nunca se confunde con la carpeta ni con el ejecutable del producto.
        assert item.executable_path.value is None
        assert item.uninstall.path.value is None

    def test_incorrect_paths_are_marked_missing(self) -> None:
        registry = registry_with(
            (
                HKLM,
                V64,
                "Rota",
                {
                    "DisplayName": "Ruta Rota",
                    "InstallLocation": "D:\\No\\Existe",
                    "DisplayIcon": "D:\\No\\Existe\\rota.exe,0",
                },
            )
        )
        item = only(collect(registry, FakeFiles())[0], "Ruta Rota")
        assert item.install_path.value == "D:\\No\\Existe"
        assert item.install_path.state is PathState.MISSING
        assert item.executable_path.value is None
        assert item.executable_path.reason == "install_path_missing_on_disk"

    def test_inaccessible_install_path(self) -> None:
        registry = registry_with(
            (HKLM, V64, "Priv", {"DisplayName": "Privada", "InstallLocation": "C:\\Priv"})
        )
        item = only(collect(registry, FakeFiles(inaccessible={"C:\\Priv"}))[0], "Privada")
        assert item.install_path.state is PathState.INACCESSIBLE
        assert item.executable_path.reason == "install_path_inaccessible"

    def test_network_path_is_not_touched(self) -> None:
        location = "\\\\servidor-ficticio\\apps\\red"
        registry = registry_with(
            (HKLM, V64, "Red", {"DisplayName": "App De Red", "InstallLocation": location})
        )
        files = FakeFiles()
        item = only(collect(registry, files)[0], "App De Red")
        assert item.install_path.state is PathState.NOT_CHECKED
        assert files.listed == []
        assert item.executable_path.value is None

    def test_per_user_software(self) -> None:
        exe = "C:\\Users\\ficticio\\AppData\\Local\\Programs\\Notas\\notas.exe"
        registry = registry_with(
            (HKCU, DEFAULT, "Notas", {"DisplayName": "Notas", "DisplayIcon": exe})
        )
        files = FakeFiles(existing={exe}, metadata_by_path={exe: FileMetadata(machine="x64")})
        item = only(collect(registry, files)[0], "Notas")
        assert item.scope is SoftwareScope.CURRENT_USER
        assert item.architecture.confidence is Confidence.VERIFIED

    def test_uninstaller_icon_is_not_the_executable(self) -> None:
        registry = registry_with(
            (
                HKLM,
                V64,
                "Ico",
                {
                    "DisplayName": "Con Icono",
                    "DisplayIcon": "C:\\Apps\\Ico\\unins000.exe,0",
                    "InstallLocation": "C:\\Apps\\Ico",
                },
            )
        )
        files = FakeFiles(
            existing={"C:\\Apps\\Ico\\unins000.exe"},
            directories={"C:\\Apps\\Ico": ["C:\\Apps\\Ico\\unins000.exe"]},
        )
        item = only(collect(registry, files)[0], "Con Icono")
        assert item.executable_path.value is None
        assert item.executable_path.reason == "no_unambiguous_executable_in_install_path"

    def test_msi_cached_icon_is_not_the_executable(self) -> None:
        icon = "C:\\Windows\\Installer\\{AAAA}\\icon.exe"
        registry = registry_with(
            (HKLM, V64, "MsiIco", {"DisplayName": "Icono Cacheado", "DisplayIcon": icon})
        )
        item = only(collect(registry, FakeFiles(existing={icon}))[0], "Icono Cacheado")
        assert item.executable_path.value is None
        assert item.install_path.value is None
        assert item.executable_path.reason == "display_icon_is_not_the_main_executable"

    def test_app_paths_resolve_executable(self) -> None:
        exe = "C:\\Apps\\Visor\\visor.exe"
        registry = registry_with(
            (HKLM, V64, "Visor", {"DisplayName": "Visor", "InstallLocation": "C:\\Apps\\Visor"})
        )
        registry.put(
            HKLM,
            V64,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\visor.exe",
            {"": exe},
        )
        files = FakeFiles(existing={exe}, directories={"C:\\Apps\\Visor": []})
        item = only(collect(registry, files)[0], "Visor")
        assert item.executable_path.value == exe
        assert item.executable_path.source == "registry:App Paths"

    def test_no_executable_stays_null_with_reason(self) -> None:
        registry = registry_with((HKLM, V64, "Lib", {"DisplayName": "Solo Librerias"}))
        item = only(collect(registry)[0], "Solo Librerias")
        assert item.executable_path.value is None
        assert item.executable_path.reason == "windows_does_not_identify_executable"
        assert item.install_path.reason == "install_location_not_reported"

    def test_version_falls_back_to_file_as_probable(self) -> None:
        exe = "C:\\Apps\\Sv\\sv.exe"
        registry = registry_with(
            (HKLM, V64, "Sv", {"DisplayName": "Sin Version", "DisplayIcon": exe})
        )
        files = FakeFiles(
            existing={exe},
            metadata_by_path={exe: FileMetadata(product_version="9.9", company_name="Ficticia SA")},
        )
        item = only(collect(registry, files)[0], "Sin Version")
        assert item.version.value == "9.9"
        assert item.version.confidence is Confidence.PROBABLE
        assert item.publisher.value == "Ficticia SA"
        assert item.publisher.confidence is Confidence.PROBABLE

    def test_missing_properties_are_declared_not_invented(self) -> None:
        registry = registry_with((HKLM, V64, "Min", {"DisplayName": "Minimo"}))
        item = only(collect(registry)[0], "Minimo")
        assert item.version.value is None
        assert item.publisher.value is None
        assert item.size_bytes.value is None
        assert item.install_date.value is None

    def test_invalid_install_date_keeps_raw(self) -> None:
        registry = registry_with(
            (HKLM, V64, "Fecha", {"DisplayName": "Fecha Rara", "InstallDate": "15/01/2026"})
        )
        item = only(collect(registry)[0], "Fecha Rara")
        assert item.install_date.value is None
        assert item.install_date.raw == "15/01/2026"

    def test_last_write_is_only_probable_install_date(self) -> None:
        registry = registry_with((HKLM, V64, "Lw", {"DisplayName": "Sin Fecha"}))
        registry.last_write_value = datetime(2026, 2, 3, tzinfo=UTC)
        item = only(collect(registry)[0], "Sin Fecha")
        assert item.install_date.value == "2026-02-03"
        assert item.install_date.confidence is Confidence.PROBABLE

    def test_entries_without_name_are_counted(self) -> None:
        registry = registry_with(
            (HKLM, V64, "Sin", {"Publisher": "Nadie"}),
            (HKLM, V64, "Con", {"DisplayName": "Con Nombre"}),
        )
        section, _ = collect(registry)
        assert section.total_count == 1
        assert section.skipped_entries_without_name == 1

    def test_system_components_and_updates_are_flagged_not_dropped(self) -> None:
        registry = registry_with(
            (HKLM, V64, "Sys", {"DisplayName": "Componente", "SystemComponent": 1}),
            (HKLM, V64, "Upd", {"DisplayName": "Parche", "ParentKeyName": "Padre"}),
        )
        section, _ = collect(registry)
        assert only(section, "Componente").is_system_component
        assert only(section, "Parche").is_update

    def test_unknown_signature_budget_is_reported(self) -> None:
        exe = "C:\\Apps\\Firma\\firma.exe"
        registry = registry_with((HKLM, V64, "F", {"DisplayName": "Firma", "DisplayIcon": exe}))
        files = FakeFiles(existing={exe}, metadata_by_path={exe: FileMetadata(machine="x64")})
        section, ctx = collect(registry, files, signatures=FakeSignatures())
        item = only(section, "Firma")
        assert item.executable.signature.status is SignatureStatus.NOT_CHECKED
        assert item.executable.signature.reason == "time_budget_exhausted"
        assert any(w.code == "signatures_incomplete" for w in ctx.warnings)

    def test_uninstall_command_is_never_executed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        def forbidden(*args: Any, **kwargs: Any) -> None:
            raise AssertionError("el inventario no debe ejecutar procesos")

        monkeypatch.setattr(subprocess, "Popen", forbidden)
        registry = registry_with(
            (
                HKLM,
                V64,
                "U",
                {
                    "DisplayName": "Peligrosa",
                    "UninstallString": "cmd.exe /c del C:\\archivo-ficticio",
                    "QuietUninstallString": "cmd.exe /c del C:\\archivo-ficticio",
                },
            )
        )
        item = only(collect(registry)[0], "Peligrosa")
        assert item.uninstall.command == "cmd.exe /c del C:\\archivo-ficticio"


class TestSourceFailures:
    def test_missing_views_are_not_errors(self) -> None:
        section, ctx = collect(FakeRegistry())
        statuses = {r.source: r.status for r in section.sources}
        assert statuses["registry:HKLM\\64"] is SoftwareSourceStatus.NOT_PRESENT
        assert statuses["appx:Get-AppxPackage"] is SoftwareSourceStatus.OK
        assert ctx.errors == []

    def test_denied_view_keeps_other_sources(self) -> None:
        registry = registry_with((HKCU, DEFAULT, "Mia", {"DisplayName": "Mia"}))
        registry.put(HKLM, V64, f"{UNINSTALL}\\X", {"DisplayName": "Oculta"})
        registry.denied.add(UNINSTALL + "_")
        section, _ = collect(registry)
        assert only(section, "Mia")

    def test_denied_entry_is_counted(self) -> None:
        registry = registry_with(
            (HKLM, V64, "Ok", {"DisplayName": "Visible"}),
            (HKLM, V64, "No", {"DisplayName": "Denegada"}),
        )
        registry.denied.add(f"{UNINSTALL}\\No")
        section, ctx = collect(registry)
        assert only(section, "Visible")
        assert any(w.code == "unreadable_entries" for w in ctx.warnings)
        assert "1 entradas" in next(r.detail for r in section.sources if r.source.endswith("64"))

    def test_registry_failure_is_isolated(self) -> None:
        registry = FakeRegistry(failing={UNINSTALL})
        appx = FakeAppx(rows=[{"Name": "App.Ficticia", "PackageFullName": "App.Ficticia_1"}])
        section, ctx = collect(registry, appx=appx)
        assert section.total_count == 1
        assert {e.code for e in ctx.errors} == {"registry_error"}

    def test_appx_failure_falls_back_to_registry_index(self) -> None:
        repository = (
            r"Software\Classes\Local Settings\Software\Microsoft\Windows\CurrentVersion"
            r"\AppModel\Repository\Packages"
        )
        registry = FakeRegistry()
        registry.put(
            HKCU,
            DEFAULT,
            repository + r"\Empresa.App_1.2.3.0_x64__abc123",
            {"PackageRootFolder": "C:\\Program Files\\WindowsApps\\Empresa.App"},
        )
        section, ctx = collect(registry, appx=FakeAppx(error=CimErrorKind.ACCESS_DENIED))
        item = only(section, "Empresa.App")
        assert item.version.value == "1.2.3.0"
        assert item.installer_type is InstallerType.MSIX
        report = next(r for r in section.sources if r.source.startswith("appx"))
        assert report.status is SoftwareSourceStatus.ACCESS_DENIED
        assert report.item_count == 1
        assert any(w.code == "appx_query_failed" for w in ctx.warnings)

    def test_all_sources_failing_is_an_error(self) -> None:
        registry = FakeRegistry(failing={UNINSTALL})
        _, ctx = collect(registry, appx=FakeAppx(error=CimErrorKind.FAILED))
        assert any(e.code == "no_software_source" for e in ctx.errors)

    def test_limitations_are_declared(self) -> None:
        section, _ = collect()
        assert any("portables" in text for text in section.limitations)


class TestAppx:
    def test_package_with_manifest(self) -> None:
        location = "C:\\Program Files\\WindowsApps\\Empresa.App_1.0_x64__abc"
        exe = location + "\\bin\\app.exe"
        manifest = """<Package><Properties><DisplayName>App Empresa</DisplayName>
        <PublisherDisplayName>Empresa SA</PublisherDisplayName></Properties>
        <Applications><Application Executable="bin/app.exe"/></Applications></Package>"""
        files = FakeFiles(
            existing={location, exe},
            texts={location + "\\AppxManifest.xml": manifest},
            metadata_by_path={exe: FileMetadata(file_version="1.0.0.0", machine="x64")},
        )
        appx = FakeAppx(
            rows=[
                {
                    "Name": "Empresa.App",
                    "Publisher": "CN=Empresa SA, O=Empresa",
                    "Version": "1.0.0.0",
                    "Architecture": "X64",
                    "InstallLocation": location,
                    "PackageFullName": "Empresa.App_1.0.0.0_x64__abc",
                    "SignatureKind": "Store",
                    "IsFramework": False,
                    "IsResourcePackage": False,
                    "NonRemovable": False,
                }
            ]
        )
        section, _ = collect(files=files, appx=appx)
        item = only(section, "App Empresa")
        assert item.installer_type is InstallerType.MSIX
        assert item.scope is SoftwareScope.CURRENT_USER
        assert item.mechanism is DetectionMechanism.APPX_PACKAGE
        assert item.publisher.value == "Empresa SA"
        assert item.architecture.value == "x64"
        assert item.executable_path.value == exe
        assert item.package_signature_kind == "Store"
        assert item.executable.file_version == "1.0.0.0"
        assert item.uninstall is None

    def test_inaccessible_manifest(self) -> None:
        appx = FakeAppx(
            rows=[{"Name": "P", "InstallLocation": "C:\\Protegido", "PackageFullName": "P_1"}]
        )
        item = only(collect(files=FakeFiles(existing={"C:\\Protegido"}), appx=appx)[0], "P")
        assert item.executable_path.value is None
        assert item.executable_path.reason == "package_manifest_not_readable"

    def test_resource_packages_are_skipped_and_frameworks_flagged(self) -> None:
        appx = FakeAppx(
            rows=[
                {"Name": "Recurso", "PackageFullName": "R", "IsResourcePackage": True},
                {"Name": "Marco", "PackageFullName": "M", "IsFramework": True},
            ]
        )
        section, _ = collect(appx=appx)
        assert section.total_count == 1
        assert only(section, "Marco").is_framework

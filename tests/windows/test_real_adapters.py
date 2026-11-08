"""Adaptadores contra el Windows real donde corre la prueba, sin mocks.

Solo comprueban forma y comportamiento: no fijan valores de ningún equipo concreto.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

from honey_check.application.ports import (
    CancelToken,
    CimErrorKind,
    CimQuery,
    CollectionCancelled,
    RegistryHive,
    RegistryKeyMissing,
    RegistryView,
)
from honey_check.domain.inventory import PathState
from honey_check.infrastructure.windows.files import WinFileInspector, read_pe_machine
from honey_check.infrastructure.windows.native import WinNativeSystem
from honey_check.infrastructure.windows.powershell import (
    PowerShell,
    PowerShellAppx,
    PowerShellCim,
    PowerShellInfo,
    PowerShellSignatures,
)
from honey_check.infrastructure.windows.process import ProcessRunner, ProcessTimeout, system32_path
from honey_check.infrastructure.windows.registry import WinRegistry

pytestmark = pytest.mark.windows_real


@pytest.fixture(scope="module")
def runner():
    instance = ProcessRunner()
    yield instance
    instance.close()


@pytest.fixture(scope="module")
def powershell(runner):
    return PowerShell(runner)


OS_QUERY = CimQuery(
    "root/cimv2", "Win32_OperatingSystem", ("Caption", "BuildNumber", "InstallDate")
)


class TestPowerShellCim:
    def test_reads_operating_system(self, powershell) -> None:
        result = PowerShellCim(powershell).query([OS_QUERY], CancelToken(), 60)[0]
        assert result.ok, result.error
        assert len(result.rows) == 1
        assert int(result.rows[0]["BuildNumber"]) >= 10240
        assert "T" in result.rows[0]["InstallDate"]

    def test_failed_class_does_not_affect_others(self, powershell) -> None:
        missing_class = CimQuery("root/cimv2", "Win32_ClaseQueNoExiste", ("X",))
        missing_namespace = CimQuery("root/no_existe", "X", ("X",))
        results = PowerShellCim(powershell).query(
            [missing_class, OS_QUERY, missing_namespace], CancelToken(), 60
        )
        assert results[0].error is not None
        assert results[0].error.kind is CimErrorKind.NOT_AVAILABLE
        assert results[1].ok
        assert results[2].error is not None
        assert results[2].error.kind is CimErrorKind.NOT_AVAILABLE

    def test_filtered_query(self, powershell) -> None:
        query = CimQuery(
            "root/cimv2", "Win32_PnPEntity", ("Name",), where="ConfigManagerErrorCode > 99"
        )
        result = PowerShellCim(powershell).query([query], CancelToken(), 60)[0]
        assert result.ok
        assert result.rows == ()

    def test_rejects_injection_in_query(self, powershell) -> None:
        bad = CimQuery("root/cimv2", "X; Remove-Item C:\\", ("Y",))
        with pytest.raises(ValueError, match="no permitida"):
            PowerShellCim(powershell).query([bad], CancelToken(), 5)

    def test_cancel_kills_process(self, powershell) -> None:
        token = CancelToken()
        token.cancel()
        with pytest.raises(CollectionCancelled):
            PowerShellCim(powershell).query([OS_QUERY], token, 30)


class TestProcessRunner:
    def test_timeout_is_enforced_and_kills(self, runner) -> None:
        args = [sys.executable, "-c", "import time; time.sleep(60)"]
        started = time.monotonic()
        with pytest.raises(ProcessTimeout):
            runner.run(args, timeout_s=0.5, cancel=CancelToken())
        assert time.monotonic() - started < 10

    def test_output_limit(self) -> None:
        from honey_check.infrastructure.windows.process import OutputTooLarge

        limited = ProcessRunner(max_output_bytes=1024)
        args = [sys.executable, "-c", "import sys; sys.stdout.write('x' * 1000000)"]
        with pytest.raises(OutputTooLarge):
            limited.run(args, timeout_s=30, cancel=CancelToken())
        limited.close()

    def test_close_rejects_new_work(self) -> None:
        closed = ProcessRunner()
        closed.close()
        with pytest.raises(CollectionCancelled):
            closed.run([sys.executable, "-V"], timeout_s=5, cancel=CancelToken())


class TestEncoding:
    def test_non_ascii_survives_roundtrip(self, powershell) -> None:
        """Los acentos y símbolos no deben depender de la página de códigos de la consola."""
        script = r"""
$value = (($input | Out-String) | ConvertFrom-Json).text
function Emit($value) {
  $json = ConvertTo-Json -InputObject $value -Depth 6 -Compress
  $chars = @([regex]::Matches($json, '[^\x00-\x7e]') | ForEach-Object { $_.Value } | Select-Object -Unique)
  foreach ($c in $chars) { $json = $json.Replace($c, ('\u{0:x4}' -f [int][char]$c)) }
  $json
}
Emit @{ text = $value }
"""
        text = "Ñandú ñandú € 日本語 🍯 Éé"
        answer = powershell.run_json(script, {"text": text}, CancelToken(), 60)
        assert answer["text"] == text

    @pytest.mark.parametrize(
        "prefix", ["$ExecutionContext.SessionState.LanguageMode='ConstrainedLanguage';"]
    )
    def test_cim_script_works_in_constrained_language(self, powershell, prefix) -> None:
        """Simula AppLocker/WDAC: el script de consulta debe funcionar sin FullLanguage."""
        from honey_check.infrastructure.windows import powershell as module

        payload = [
            {
                "namespace": "root/cimv2",
                "class": "Win32_OperatingSystem",
                "properties": ["Caption", "InstallDate"],
                "where": None,
                "timeout": 30,
            }
        ]
        answer = powershell.run_json(prefix + module._CIM_SCRIPT, payload, CancelToken(), 60)
        row = answer["results"][0] if isinstance(answer["results"], list) else answer["results"]
        assert row["ok"] is True
        rows = row["rows"] if isinstance(row["rows"], list) else [row["rows"]]
        assert "T" in rows[0]["InstallDate"]

    @pytest.mark.parametrize(
        "prefix", ["$ExecutionContext.SessionState.LanguageMode='ConstrainedLanguage';"]
    )
    def test_appx_script_works_in_constrained_language(self, powershell, prefix) -> None:
        from honey_check.infrastructure.windows import powershell as module

        answer = powershell.run_json(prefix + module._APPX_SCRIPT, None, CancelToken(), 90)
        assert "rows" in answer


class TestSignatures:
    def test_signed_system_binary(self, powershell) -> None:
        path = str(system32_path("notepad.exe"))
        if not Path(path).exists():
            path = str(system32_path("cmd.exe"))
        found = PowerShellSignatures(powershell).inspect([path], CancelToken(), 60)
        assert found[path].status == "valid"

    def test_hostile_path_is_data_not_code(self, powershell, tmp_path) -> None:
        canary = tmp_path / "canary.txt"
        hostile = f"C:\\x'; New-Item -Path '{canary}' -ItemType File; '"
        found = PowerShellSignatures(powershell).inspect([hostile], CancelToken(), 60)
        assert found[hostile].status != "valid"
        assert not canary.exists()


class TestAppx:
    def test_returns_list(self, powershell) -> None:
        packages = PowerShellAppx(powershell).packages(CancelToken(), 90)
        assert isinstance(packages, list)
        for package in packages[:5]:
            assert package["PackageFullName"]

    def test_language_mode(self, powershell) -> None:
        mode = PowerShellInfo(powershell).language_mode(CancelToken(), 60)
        assert mode in ("FullLanguage", "ConstrainedLanguage", "RestrictedLanguage", "NoLanguage")


class TestRegistry:
    PATH = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"

    def test_reads_uninstall_views(self) -> None:
        registry = WinRegistry()
        names = registry.subkeys(RegistryHive.LOCAL_MACHINE, self.PATH, RegistryView.BITS_64)
        assert isinstance(names, list)

    def test_reads_current_version_values(self) -> None:
        values = WinRegistry().values(
            RegistryHive.LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
            RegistryView.DEFAULT,
        )
        assert values["CurrentBuild"]
        assert isinstance(values["UBR"], int)

    def test_missing_key(self) -> None:
        with pytest.raises(RegistryKeyMissing):
            WinRegistry().subkeys(
                RegistryHive.CURRENT_USER, r"Software\HoneyCheck\NoExiste", RegistryView.DEFAULT
            )

    def test_last_write(self) -> None:
        moment = WinRegistry().last_write(
            RegistryHive.LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
            RegistryView.DEFAULT,
        )
        assert moment is not None
        assert moment.year >= 2015


class TestFiles:
    def test_path_states(self, tmp_path) -> None:
        inspector = WinFileInspector()
        assert inspector.path_state(str(tmp_path)) is PathState.VALID
        assert inspector.path_state(str(tmp_path / "no-existe.exe")) is PathState.MISSING
        assert (
            inspector.path_state(r"\\servidor-ficticio\compartido\a.exe") is PathState.NOT_CHECKED
        )

    def test_system_binary_metadata(self) -> None:
        metadata = WinFileInspector().metadata(str(system32_path("cmd.exe")))
        assert metadata.file_version
        assert metadata.company_name
        assert metadata.machine in ("x64", "arm64")

    def test_list_executables(self) -> None:
        found = WinFileInspector().list_executables(str(system32_path()), 4000)
        assert any(Path(p).name.lower() == "cmd.exe" for p in found)

    def test_list_is_bounded(self) -> None:
        found = WinFileInspector().list_executables(str(system32_path()), 5)
        assert len(found) <= 5

    def test_pe_machine_rejects_non_pe(self, tmp_path) -> None:
        fake = tmp_path / "fake.exe"
        fake.write_bytes(b"esto no es un ejecutable")
        assert read_pe_machine(str(fake)) is None

    def test_read_text_is_bounded(self, tmp_path) -> None:
        big = tmp_path / "big.txt"
        big.write_text("x" * 2048)
        assert WinFileInspector().read_text(str(big), 1024) is None
        assert WinFileInspector().read_text(str(big), 4096) == "x" * 2048


class TestNative:
    def test_values(self) -> None:
        native = WinNativeSystem()
        assert native.computer_name()
        assert native.firmware_mode() in ("uefi", "legacy_bios", None)
        assert native.native_architecture() in ("x64", "arm64", "x86", "arm")
        assert native.is_elevated() in (True, False)

    def test_tpm_info_does_not_crash(self) -> None:
        info = WinNativeSystem().tpm_info()
        assert info is None or isinstance(info.present, bool)

    def test_display_modes_positive(self) -> None:
        for mode in WinNativeSystem().display_modes():
            assert mode.width > 0
            assert mode.height > 0
            json.dumps({"device": mode.device})


class TestInheritedEnvironment:
    def test_module_path_of_powershell_7_does_not_break_system_modules(self, monkeypatch) -> None:
        """Con PSModulePath ajeno, Windows PowerShell no podía cargar sus módulos de sistema."""
        monkeypatch.setenv("PSModulePath", r"C:\ruta-ficticia\PowerShell\7\Modules")
        isolated = ProcessRunner()
        path = str(system32_path("cmd.exe"))
        found = PowerShellSignatures(PowerShell(isolated)).inspect([path], CancelToken(), 60)
        isolated.close()
        assert found[path].status == "valid"


def test_disks_and_partitions_include_the_system_drive() -> None:
    """Cada disco físico con sus particiones, sin administrador; la del sistema tiene su letra."""
    import os

    from honey_check.infrastructure.windows.volumes import list_disks

    disks = list_disks()
    assert disks
    system = os.environ.get("SYSTEMDRIVE", "C:")[0].upper()
    roots = [p for d in disks for p in d.partitions if p.letter == system]
    assert len(roots) == 1
    assert roots[0].size > 0 and roots[0].free is not None
    assert roots[0].file_system

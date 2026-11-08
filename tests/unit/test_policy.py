"""Política de seguridad comprobada sobre el propio código fuente."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parents[2] / "src" / "honey_check"
TOOLS = Path(__file__).parents[2] / "tools"
SOURCES = list(SRC.rglob("*.py"))
UI_SRC = SRC.parents[1] / "ui" / "src"
WEB = sorted(p for p in UI_SRC.rglob("*") if p.suffix in {".html", ".ts", ".vue", ".css"})
UI_INDEX = SRC.parents[1] / "ui" / "index.html"


def code_of(path: Path) -> str:
    """Quita comentarios y docstrings: la prohibición se aplica a lo que se ejecuta."""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r'"""[\s\S]*?"""', "", text)
    return re.sub(r"(?m)#.*$", "", text)


# El soporte (herramientas que el técnico ejecuta con plan y confirmación) puede cambiar el
# equipo. El inventario y el resto del producto solo leen.
SUPPORT_DIRS = (SRC / "application" / "support", SRC / "infrastructure" / "support")
SUPPORT_FILES = {
    SRC / "domain" / "support.py",
    SRC / "domain" / "procedures.py",
    SRC / "presentation" / "http" / "support_routes.py",
    SRC / "infrastructure" / "windows" / "shell.py",
    SRC / "infrastructure" / "windows" / "credentials.py",
    SRC / "infrastructure" / "windows" / "netdiag.py",
    # Traduce códigos de SHFileOperation y de instaladores; cierra procesos (Restart Manager).
    SRC / "infrastructure" / "windows" / "errors.py",
    SRC / "infrastructure" / "windows" / "locks.py",
}


def is_support(path: Path) -> bool:
    return path in SUPPORT_FILES or any(folder in path.parents for folder in SUPPORT_DIRS)


INVENTORY = [p for p in SOURCES if not is_support(p)]

# La única excepción: relanzar Honey Check con el aviso UAC cuando el técnico lo pide.
ELEVATION_ONLY = {"elevation.py"}


@pytest.mark.parametrize(
    "forbidden",
    [
        # Ocultar o saltarse controles: prohibido en todo el producto, también en soporte.
        r"Win32_Product",
        r"-EncodedCommand",
        r"-ExecutionPolicy",
        r"Set-ExecutionPolicy",
        r"Start-Process",
        r"Invoke-Expression",
        r"\biex\b",
        r"\brunas\b",
        r"ShellExecute",
        r"bcdedit",
        r"Set-MpPreference|Add-MpPreference|DisableRealtimeMonitoring",
        r"Set-GPRegistryValue|Registry\.pol|secedit\b",
        r"Set-AppLockerPolicy|Set-RuleOption|Set-CIPolicy|citool",
        r"wevtutil(\.exe)?\"?,?\s*\"?(cl|clear-log)\b|Clear-EventLog|Clear-WinEvent",
        r"shell=True",
        r"\bopentelemetry\b",
        r"\beval\(|\bexec\(",
    ],
)
def test_forbidden_mechanisms_are_absent(forbidden: str) -> None:
    pattern = re.compile(forbidden, re.IGNORECASE)
    allowed = ELEVATION_ONLY if forbidden in {r"\brunas\b", r"ShellExecute"} else set()
    if forbidden.startswith("Set-GPRegistryValue"):
        # Registry.pol dañado: solo el solucionador de directivas lo respalda y renombra.
        allowed = {"policies.py"}
    offenders = [p.name for p in SOURCES if pattern.search(code_of(p)) and p.name not in allowed]
    assert offenders == []


@pytest.mark.parametrize(
    "change",
    [
        r"msiexec(?!\.exe\")",
        r"\bSet-Item",
        r"\bNew-ItemProperty",
        r"\bSet-ItemProperty",
        r"\bRemove-Item",
        r"reg(\.exe)? (add|delete)",
        r"shutdown(\.exe)? /|Restart-Computer|gpupdate",
        r"winreg\.(SetValue|SetValueEx|CreateKey|CreateKeyEx|DeleteKey|DeleteValue)",
        r"KEY_(WRITE|SET_VALUE|CREATE_SUB_KEY|ALL_ACCESS)",
        r"SHFileOperation|SHEmptyRecycleBin|CredDelete|RegDeleteTree|DnsFlushResolverCache",
    ],
)
def test_inventory_only_reads(change: str) -> None:
    pattern = re.compile(change, re.IGNORECASE)
    assert [p.name for p in INVENTORY if pattern.search(code_of(p))] == []


def test_support_never_writes_group_policy_keys() -> None:
    registry = code_of(SRC / "infrastructure" / "support" / "tools" / "registry.py")
    for writer in ("def _set(", "def _delete("):
        body = registry.split(writer, 1)[1].split("\ndef ", 1)[0]
        assert "refuse_policy(short)" in body, writer


def test_support_commands_are_argument_lists_with_absolute_programs() -> None:
    """Las herramientas lanzan programas con ruta completa y argumentos como lista."""
    for path in (SRC / "infrastructure" / "support").rglob("*.py"):
        code = code_of(path)
        assert "subprocess" not in code, path.name  # todo pasa por ctx.command y su registro
        assert not re.search(r"ctx\.command\(\s*[\"f]", code), path.name


def test_elevation_only_relaunches_honey_check_itself() -> None:
    callers = [p.name for p in SOURCES if "launch_elevated(" in code_of(p)]
    assert sorted(callers) == ["app.py", "elevation.py"]
    app = code_of(SRC / "app.py")
    assert "launch_elevated(sys.executable, arguments, str(self._base_dir))" in app


@pytest.mark.parametrize(
    "forbidden",
    ["requests", "urllib.request", "httpx", "aiohttp", "smtplib", "ftplib", "sentry", "telemetry"],
)
def test_no_outbound_network_client_in_the_product(forbidden: str) -> None:
    pattern = re.compile(rf"^\s*(import|from)\s+{re.escape(forbidden)}", re.MULTILINE)
    assert [p.name for p in SOURCES if pattern.search(code_of(p))] == []


@pytest.mark.parametrize("path", WEB, ids=lambda p: p.name)
def test_interface_has_no_external_resources(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    urls = re.findall(r"https?://[^\s\"')]+", text)
    assert [u for u in urls if not u.startswith("http://www.w3.org/")] == []


@pytest.mark.parametrize("path", WEB, ids=lambda p: p.name)
def test_interface_never_injects_html(path: Path) -> None:
    script = re.sub(r"(?m)^\s*//.*$", "", path.read_text(encoding="utf-8"))
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "v-html",
        "eval(",
        "new Function",
    ):
        assert forbidden not in script


def test_html_has_no_inline_script_or_style() -> None:
    html = UI_INDEX.read_text(encoding="utf-8")
    assert "<style" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert not re.search(r"\son\w+=", html)


def test_server_binds_only_to_loopback() -> None:
    server = (SRC / "presentation" / "http" / "server.py").read_text(encoding="utf-8")
    assert 'LOOPBACK = "127.0.0.1"' in server
    assert "0.0.0.0" not in server  # noqa: S104
    assert "sock.bind((LOOPBACK, 0))" in server


def test_powershell_scripts_only_read() -> None:
    from honey_check.infrastructure.windows import powershell

    for script in (
        powershell._CIM_SCRIPT,
        powershell._SIGNATURE_SCRIPT,
        powershell._APPX_SCRIPT,
        powershell._LANGUAGE_MODE_SCRIPT,
    ):
        verbs = set(re.findall(r"\b([A-Z][a-z]+)-[A-Z][A-Za-z]+\b", script))
        assert verbs <= {"Get", "ConvertTo", "ConvertFrom", "Select", "ForEach", "Out"}, verbs


def _licenses_module():
    spec = importlib.util.spec_from_file_location("licenses", TOOLS / "licenses.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["licenses"] = module
    spec.loader.exec_module(module)
    return module


def test_runtime_dependencies_comply_with_license_and_telemetry_policy() -> None:
    licenses = _licenses_module()
    packages = licenses.runtime_packages()
    assert {"starlette", "uvicorn", "pydantic"} <= {p.name for p in packages}
    assert licenses.policy_violations(packages) == []
    assert all(p.license_text.strip() for p in packages), [
        p.name for p in packages if not p.license_text.strip()
    ]


@pytest.mark.parametrize(
    ("name", "license_text"),
    [
        ("libreria", "LGPLv3"),
        ("libreria", "GNU Lesser General Public License v3 (LGPLv3)"),
        ("libreria", "GPL-3.0-only"),
        ("opentelemetry-api", "Apache-2.0"),
    ],
)
def test_policy_rejects_copyleft_and_telemetry(name: str, license_text: str) -> None:
    licenses = _licenses_module()
    package = licenses.Package(name, "1.0", license_text, "")
    assert licenses.policy_violations([package])


def test_policy_accepts_permissive_licenses() -> None:
    licenses = _licenses_module()
    assert licenses.policy_violations([licenses.Package("x", "1", "MIT", "")]) == []


def test_registry_pol_is_only_backed_up_and_renamed_when_damaged() -> None:
    """El único uso de Registry.pol: validar la cabecera, respaldar y renombrar; nunca escribirlo."""
    code = code_of(SRC / "infrastructure" / "support" / "tools" / "policies.py")
    assert 'REGISTRY_POL_HEADER = b"PReg' in code
    fix = code.split("def _fix_pol(", 1)[1].split("\ndef ", 1)[0]
    assert fix.index("shutil.copy2(") < fix.index(".rename(")
    for writer in ("write_bytes", "write_text", '"wb"', '"w"', "unlink("):
        assert writer not in fix, writer


def test_instant_tools_have_nothing_to_review() -> None:
    """Una herramienta inmediata corre con el clic, sin revisión: nunca borra ni pide administrador."""
    from honey_check.domain.support import Risk
    from honey_check.infrastructure.support.tools import (
        cleanup,
        disk,
        network,
        printers,
        programs,
        registry,
        software,
        system,
    )

    every = [
        t.definition
        for module in (cleanup, disk, network, printers, programs, registry, software, system)
        for t in module.TOOLS
    ]
    instant = [d for d in every if d.instant]
    assert {t.id for t in instant} >= {"explorer.open", "network.flush_dns"}
    for definition in instant:
        assert definition.risk is not Risk.DESTRUCTIVE, definition.id
        assert not definition.requires_admin, definition.id

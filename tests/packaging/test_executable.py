"""Prueba de caja negra del .exe construido, copiado a una carpeta que simula una USB.

Requiere `HONEY_CHECK_EXE` con la ruta del ejecutable; sin ella estas pruebas se omiten.
Consulta el Windows real del equipo, así que los inventarios que genera son datos reales: se
escriben en una carpeta temporal, nunca en el repositorio, y aquí no se fijan valores concretos.
"""

from __future__ import annotations

import http.client
import http.cookiejar
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from honey_check.domain.inventory import CollectionStatus, Inventory, ModuleStatus
from honey_check.domain.migrations import load_document

pytestmark = pytest.mark.packaging

EXE_ENV = os.environ.get("HONEY_CHECK_EXE")
SCAN_TIMEOUT_S = 420.0
STARTUP_TIMEOUT_S = 90.0


@pytest.fixture(scope="module")
def built_exe() -> Path:
    if not EXE_ENV:
        pytest.skip("HONEY_CHECK_EXE no está definido")
    path = Path(EXE_ENV)
    assert path.is_file(), path
    return path


@dataclass
class Running:
    process: subprocess.Popen[bytes]
    folder: Path
    base: str
    port: int
    opener: urllib.request.OpenerDirector
    temp_dir: Path
    csrf: str = field(default="", repr=False)

    def request(self, path: str, method: str = "GET", body: Any = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(f"{self.base}{path}", data=data, method=method)
        if method != "GET":
            request.add_header("Origin", self.base)
            request.add_header("X-Honey-Check-CSRF", self.csrf)
            request.add_header("Content-Length", str(len(data or b"")))
            if data:
                request.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            raw = error.read()
            status = error.code
        if raw.startswith((b"{", b"[")):
            return status, json.loads(raw)
        return status, raw


def launch(
    exe: Path, folder: Path, status_file: Path, temp_dir: Path, *extra: str
) -> subprocess.Popen[bytes]:
    # Temporales propios: permite comprobar que la extracción del ejecutable no deja restos.
    env = {**os.environ, "TEMP": str(temp_dir), "TMP": str(temp_dir)}
    return subprocess.Popen(
        [str(exe), "--no-browser", "--no-tray", "--status-file", str(status_file), *extra],
        cwd=str(folder),
        env=env,
    )


def kill_tree(process: subprocess.Popen[bytes]) -> None:
    """Cierra el proceso y cualquier hijo, para no dejar huérfanos entre pruebas."""
    if process.poll() is None:
        subprocess.run(  # noqa: S603
            [r"C:\Windows\System32	askkill.exe", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        process.wait(10)


def rename_when_released(folder: Path, target: Path, timeout_s: float = 15.0) -> None:
    """Windows libera las DLL de la carpeta portable (y el antivirus termina de revisarlas) un
    momento después de que el proceso sale; se reintenta como haría el técnico al expulsar."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            folder.rename(target)
            return
        except PermissionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def authenticated_opener(entry_url: str) -> urllib.request.OpenerDirector:
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    with opener.open(entry_url, timeout=30) as response:
        assert response.status == 200
    return opener


def wait_for_file(path: Path, process: subprocess.Popen[bytes]) -> dict[str, Any]:
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        assert process.poll() is None, f"terminó con {process.returncode} antes de arrancar"
        time.sleep(0.2)
    raise AssertionError("el ejecutable no publicó su estado a tiempo")


@pytest.fixture(scope="module")
def running(
    built_exe: Path, tmp_path_factory: pytest.TempPathFactory, exe_copy_root_module: Path
) -> Iterator[Running]:
    # Ruta con espacios y acentos, como puede ocurrir en una USB real.
    folder = exe_copy_root_module / "Técnico USB Ñ"
    # La carpeta portable completa: el ejecutable y sus componentes, como queda en la USB.
    shutil.copytree(built_exe.parent, folder, ignore=shutil.ignore_patterns("HoneyCheck-datos"))
    exe = folder / "HoneyCheck.exe"
    status_file = tmp_path_factory.mktemp("estado") / "estado.json"
    temp_dir = tmp_path_factory.mktemp("temporales")
    process = launch(exe, folder, status_file, temp_dir)
    try:
        info = wait_for_file(status_file, process)
        base = f"http://127.0.0.1:{info['port']}"
        opener = authenticated_opener(info["url"])
        instance = Running(process, folder, base, info["port"], opener, temp_dir)
        status, session = instance.request("/api/session")
        assert status == 200
        instance.csrf = session["csrfToken"]
        yield instance
    finally:
        kill_tree(process)


def assert_hardware_collection(inventory: Inventory) -> None:
    """A bounded timeout is a declared partial result, never a silently missing section."""
    reports = {report.name: report for report in inventory.modules}
    collection_status = inventory.collection.status
    for name in ("processor", "memory", "storage"):
        report = reports.get(name)
        assert report is not None, (name, "missing_module_report")
        present = getattr(inventory.hardware, name) is not None
        timeout_evidence = any(
            error.module == name and error.code == "module_timeout" for error in inventory.errors
        )
        diagnostic = {
            "module": name,
            "status": report.status.value,
            "durationMs": report.duration_ms,
            "sectionPresent": present,
            "timeoutEvidence": timeout_evidence,
        }
        if present:
            assert report.status in (ModuleStatus.OK, ModuleStatus.PARTIAL), diagnostic
            assert not timeout_evidence, diagnostic
        else:
            assert report.status is ModuleStatus.TIMEOUT, diagnostic
            assert collection_status is CollectionStatus.PARTIAL, diagnostic
            assert timeout_evidence, diagnostic


class TestBundle:
    def test_size_is_reasonable(self, built_exe: Path) -> None:
        total = sum(path.stat().st_size for path in built_exe.parent.rglob("*") if path.is_file())
        assert total < 120 * 1024 * 1024

    def test_portable_folder_is_complete(self, built_exe: Path) -> None:
        folder = built_exe.parent
        for name in (
            "componentes",
            "THIRD_PARTY_LICENSES.txt",
            "build-manifest.json",
            "SHA256SUMS.txt",
        ):
            assert (folder / name).exists(), name
        listed = (folder / "SHA256SUMS.txt").read_text(encoding="utf-8")
        assert "HoneyCheck.exe" in listed
        assert "componentes/" in listed

    def test_notices_are_published_next_to_the_executable(self, built_exe: Path) -> None:
        notices = built_exe.parent / "THIRD_PARTY_LICENSES.txt"
        if not notices.is_file():
            pytest.skip("El aviso se distribuye junto al ejecutable, no se incrusta")
        text = notices.read_text(encoding="utf-8")
        assert "starlette" in text
        assert "pystray" not in text
        assert "opentelemetry" not in text

    def test_interface_travels_inside_the_executable(self, built_exe: Path) -> None:
        # Una actualización normal reemplaza solo HoneyCheck.exe: la interfaz no está en componentes.
        components = built_exe.parent / "componentes"
        assert not (components / "honey_check" / "presentation" / "web" / "dist").exists()
        manifest = json.loads((built_exe.parent / "build-manifest.json").read_text("utf-8"))
        marker = components / "huella-componentes.txt"
        assert marker.read_text(encoding="utf-8").strip() == manifest["componentsFingerprint"]

    def test_refuses_components_of_another_build(
        self, built_exe: Path, tmp_path: Path, exe_copy_root: Path
    ) -> None:
        folder = exe_copy_root / "HoneyCheck"
        shutil.copytree(built_exe.parent, folder, ignore=shutil.ignore_patterns("HoneyCheck-datos"))
        (folder / "componentes" / "huella-componentes.txt").write_text("otra", encoding="utf-8")
        status_file = tmp_path / "estado.json"
        process = launch(folder / "HoneyCheck.exe", folder, status_file, tmp_path)
        try:
            assert process.wait(60) == 3
        finally:
            kill_tree(process)
        assert json.loads(status_file.read_text(encoding="utf-8")) == {
            "error": "components_mismatch"
        }
        assert not (folder / "HoneyCheck-datos").exists()

    def test_starts_without_elevation_manifest(self, built_exe: Path) -> None:
        content = built_exe.read_bytes()
        assert b'level="requireAdministrator"' not in content
        assert b'level="highestAvailable"' not in content


class TestRunningExecutable:
    def test_interface_resources_are_bundled(self, running: Running) -> None:
        status, page = running.request("/")
        assert status == 200
        assert b"Honey Check" in page
        assets = re.findall(rb'(?:src|href)="(/assets/[^"]+)"', page)
        assert any(path.endswith(b".js") for path in assets)
        assert any(path.endswith(b".css") for path in assets)
        for path in assets:
            assert running.request(path.decode())[0] == 200
        status, icon = running.request("/icon.svg")
        assert status == 200
        assert b"<svg" in icon

    def test_only_listens_on_loopback(self, running: Running) -> None:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
            if not info[4][0].startswith("127.")
        }
        for address in addresses:
            with socket.socket() as probe:
                probe.settimeout(1)
                assert probe.connect_ex((address, running.port)) != 0

    def test_rejects_foreign_host(self, running: Running) -> None:
        connection = http.client.HTTPConnection("127.0.0.1", running.port, timeout=5)
        connection.request("GET", "/api/status", headers={"Host": "evil.example"})
        assert connection.getresponse().status == 403
        connection.close()

    def test_second_launch_does_not_start_another_server(
        self, running: Running, built_exe: Path, tmp_path: Path
    ) -> None:
        status_file = tmp_path / "segundo.json"
        second = launch(running.folder / "HoneyCheck.exe", running.folder, status_file, tmp_path)
        assert second.wait(60) == 0
        assert not status_file.exists()

    def test_scan_exports_json_next_to_the_executable(self, running: Running) -> None:
        status, _ = running.request("/api/scans", "POST")
        assert status == 202
        deadline = time.monotonic() + SCAN_TIMEOUT_S
        while time.monotonic() < deadline:
            _, current = running.request("/api/status")
            if current["scan"]["state"] not in ("running", "cancelling"):
                break
            time.sleep(1)
        assert current["scan"]["state"] == "finished", current["scan"]
        data = running.folder / "HoneyCheck-datos"
        files = list(data.glob("equipos/*/inventarios/v*.json"))
        assert len(files) == 1
        inventory = load_document(json.loads(files[0].read_text(encoding="utf-8")))
        assert inventory.collection.app_version
        assert inventory.collection.app_commit
        assert inventory.device is not None
        assert inventory.device.hostname.value
        assert inventory.operating_system is not None
        assert inventory.software is not None
        assert inventory.software.total_count > 0
        assert_hardware_collection(inventory)
        # Ningún archivo temporal queda en la carpeta de datos.
        assert not list(data.rglob("*.tmp"))
        assert (data / "logs" / "honey-check.log").is_file()

    def test_clean_exit_releases_port_and_files(self, running: Running) -> None:
        status, _ = running.request("/api/exit", "POST")
        assert status == 202
        assert running.process.wait(45) == 0
        with socket.socket() as probe:
            probe.settimeout(1)
            assert probe.connect_ex(("127.0.0.1", running.port)) != 0
        # La carpeta queda libre: se puede renombrar, como al expulsar la USB.
        renamed = running.folder.with_name("usb-liberada")
        rename_when_released(running.folder, renamed)
        running.folder = renamed
        # La carpeta portable no se descomprime en los temporales del equipo.
        assert not list(running.temp_dir.glob("_MEI*"))
        assert (renamed / "componentes").is_dir()
        # Salir también libera la instancia única.
        status_file = renamed.parent / "tercero.json"
        third = launch(renamed / "HoneyCheck.exe", renamed, status_file, running.temp_dir)
        try:
            info = wait_for_file(status_file, third)
            base = f"http://127.0.0.1:{info['port']}"
            successor = Running(
                third,
                renamed,
                base,
                info["port"],
                authenticated_opener(info["url"]),
                running.temp_dir,
            )
            _, session = successor.request("/api/session")
            successor.csrf = session["csrfToken"]
            status, _ = successor.request("/api/exit", "POST")
            assert status == 202
            assert third.wait(45) == 0
        finally:
            kill_tree(third)

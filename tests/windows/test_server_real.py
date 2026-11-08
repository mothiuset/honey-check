"""Servidor real sobre un socket real de este Windows, sin mocks de red."""

from __future__ import annotations

import http.client
import socket
from pathlib import Path

import pytest

from fakes import FakeCim, make_ports
from fixtures.vendors import HP
from honey_check.application.scan import ScanCoordinator
from honey_check.application.service import InventoryService
from honey_check.composition import default_collectors
from honey_check.infrastructure.device_store import (
    DeviceInventoryStore,
    InventoryNotFound,
    InventoryUnreadable,
    is_directory_writable,
)
from honey_check.presentation.http.app import AppCallbacks, create_app
from honey_check.presentation.http.security import SessionGuard
from honey_check.presentation.http.server import (
    LOOPBACK,
    LocalServer,
    ServerStartError,
    bind_loopback_socket,
    probe_health,
)

pytestmark = pytest.mark.windows_real


def make_server(tmp_path: Path, **kwargs: object) -> tuple[LocalServer, SessionGuard]:
    guard = SessionGuard()
    service = InventoryService(
        DeviceInventoryStore(tmp_path),
        lambda done: ScanCoordinator(
            default_collectors(), make_ports(cim=FakeCim(HP)), "0", None, done
        ),
        is_directory_writable,
        is_network_path=lambda _: False,
    )

    def factory(port: object) -> object:
        return create_app(
            service,
            guard,
            port,  # type: ignore[arg-type]
            "0",
            AppCallbacks(lambda _: None, lambda: None),
            (InventoryNotFound, InventoryUnreadable),
        )

    return LocalServer(factory, guard.instance_id, **kwargs), guard  # type: ignore[arg-type]


def can_connect(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(1)
        return probe.connect_ex((LOOPBACK, port)) == 0


class TestPortSelection:
    def test_os_assigns_port_and_only_binds_loopback(self) -> None:
        sock = bind_loopback_socket()
        try:
            host, port = sock.getsockname()
            assert host == "127.0.0.1"
            assert port > 0
        finally:
            sock.close()

    def test_two_sockets_get_different_ports(self) -> None:
        first, second = bind_loopback_socket(), bind_loopback_socket()
        try:
            assert first.getsockname()[1] != second.getsockname()[1]
        finally:
            first.close()
            second.close()

    def test_busy_ports_do_not_matter(self) -> None:
        busy = [bind_loopback_socket() for _ in range(5)]
        try:
            fresh = bind_loopback_socket()
            assert fresh.getsockname()[1] not in {s.getsockname()[1] for s in busy}
            fresh.close()
        finally:
            for sock in busy:
                sock.close()

    def test_port_cannot_be_hijacked_while_bound(self) -> None:
        owner = bind_loopback_socket()
        port = owner.getsockname()[1]
        intruder = socket.socket()
        try:
            with pytest.raises(OSError):
                intruder.bind((LOOPBACK, port))
        finally:
            intruder.close()
            owner.close()


class TestLifecycle:
    def test_start_serve_and_stop(self, tmp_path: Path) -> None:
        server, guard = make_server(tmp_path)
        server.start()
        port = server.port
        try:
            assert server.base_url == f"http://127.0.0.1:{port}"
            assert probe_health(port, guard.instance_id)
            assert not probe_health(port, "otra-instancia")
            assert server.is_healthy()
        finally:
            server.stop()
        assert not can_connect(port)
        assert not server.is_healthy() or server.port == port and not can_connect(port)

    def test_not_reachable_from_non_loopback_address(self, tmp_path: Path) -> None:
        server, _ = make_server(tmp_path)
        server.start()
        try:
            addresses = {
                info[4][0]
                for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
                if not info[4][0].startswith("127.")
            }
            for address in addresses:
                with socket.socket() as probe:
                    probe.settimeout(1)
                    assert probe.connect_ex((address, server.port)) != 0
        finally:
            server.stop()

    def test_first_start_failure_recovers(self, tmp_path: Path) -> None:
        attempts: list[int] = []

        def flaky_bind() -> socket.socket:
            attempts.append(1)
            if len(attempts) == 1:
                raise OSError("fallo simulado de arranque")
            return bind_loopback_socket()

        server, guard = make_server(tmp_path, bind=flaky_bind)
        server.start()
        try:
            assert len(attempts) == 2
            assert probe_health(server.port, guard.instance_id)
        finally:
            server.stop()

    def test_permanent_failure_is_reported(self, tmp_path: Path) -> None:
        def broken_bind() -> socket.socket:
            raise OSError("fallo simulado")

        server, _ = make_server(tmp_path, bind=broken_bind)
        with pytest.raises(ServerStartError):
            server.start()

    def test_real_http_rejects_foreign_host(self, tmp_path: Path) -> None:
        server, _ = make_server(tmp_path)
        server.start()
        try:
            connection = http.client.HTTPConnection(LOOPBACK, server.port, timeout=5)
            connection.request("GET", "/api/status", headers={"Host": "evil.example"})
            response = connection.getresponse()
            assert response.status == 403
            assert response.getheader("server") is None
            connection.close()
        finally:
            server.stop()

    def test_stop_is_idempotent(self, tmp_path: Path) -> None:
        server, _ = make_server(tmp_path)
        server.start()
        server.stop()
        server.stop()

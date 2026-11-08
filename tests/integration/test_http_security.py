"""Seguridad de los endpoints locales, con la aplicación real y el análisis simulado."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient

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
from honey_check.presentation.http.security import CSRF_HEADER, SessionGuard, cookie_name

PORT = 54321
HOST = f"127.0.0.1:{PORT}"
ORIGIN = f"http://{HOST}"


class _Opened(list):
    """Lista de carpetas abiertas; una prueba puede sustituir `append` para simular un fallo."""


class Harness:
    def __init__(self, directory: Path, *, elevated: bool | None = False) -> None:
        self.directory = directory
        self.exit_requests = 0
        self.elevations = 0
        self.accept_elevation = True
        self.elevated = elevated
        self.opened = _Opened()
        self.guard = SessionGuard()
        self.service = InventoryService(
            DeviceInventoryStore(directory / "HoneyCheck-datos"),
            lambda done: ScanCoordinator(
                default_collectors(), make_ports(cim=FakeCim(HP)), "0.1.0", None, done
            ),
            is_directory_writable,
            is_network_path=lambda _: False,
        )
        app = create_app(
            self.service,
            self.guard,
            lambda: PORT,
            "0.1.0",
            AppCallbacks(
                lambda path: self.opened.append(path),
                self._exit,
                self._elevate,
                lambda: self.elevated,
                lambda kind, title, _f: rf"D:\Elegida\{kind}-{title}",
            ),
            (InventoryNotFound, InventoryUnreadable),
        )
        self.client = TestClient(app, base_url=ORIGIN, follow_redirects=False)

    def _exit(self) -> None:
        self.exit_requests += 1

    def _elevate(self) -> bool:
        self.elevations += 1
        return self.accept_elevation

    def login(self) -> None:
        ticket = self.guard.issue_ticket()
        response = self.client.get(f"/auth/{ticket}")
        assert response.status_code == 303

    def post(self, path: str, **kwargs: Any) -> Any:
        headers = {
            CSRF_HEADER: self.guard.csrf_token,
            "Origin": ORIGIN,
            **kwargs.pop("headers", {}),
        }
        return self.client.post(path, headers=headers, **kwargs)

    def scan(self) -> None:
        assert self.post("/api/scans").status_code == 202
        assert self.service.scans.wait(30)


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


class TestSession:
    def test_health_is_public_and_reveals_nothing(self, harness: Harness) -> None:
        response = harness.client.get("/health")
        assert response.status_code == 200
        assert set(response.json()) == {"status", "app", "instance"}

    @pytest.mark.parametrize(
        "path",
        [
            "/api/session",
            "/api/status",
            "/api/inventories",
            "/api/pending",
            "/api/inventories/honey-check_x",
            "/api/comparison?base=honey-check_a&target=honey-check_b",
        ],
    )
    def test_api_requires_session(self, harness: Harness, path: str) -> None:
        assert harness.client.get(path).status_code == 401

    def test_ui_without_session_explains_how_to_enter(self, harness: Harness) -> None:
        response = harness.client.get("/")
        assert response.status_code == 401
        assert "bandeja" in response.text

    def test_ticket_is_single_use(self, harness: Harness) -> None:
        ticket = harness.guard.issue_ticket()
        assert harness.client.get(f"/auth/{ticket}").status_code == 303
        harness.client.cookies.clear()
        assert harness.client.get(f"/auth/{ticket}").status_code == 401

    def test_invalid_ticket(self, harness: Harness) -> None:
        assert harness.client.get("/auth/inventado").status_code == 401

    def test_expired_ticket(self, harness: Harness, monkeypatch: pytest.MonkeyPatch) -> None:
        from honey_check.presentation.http import security

        ticket = harness.guard.issue_ticket()
        real = security.time.monotonic()
        monkeypatch.setattr(security.time, "monotonic", lambda: real + 3600)
        assert harness.client.get(f"/auth/{ticket}").status_code == 401

    def test_cookie_is_hardened(self, harness: Harness) -> None:
        response = harness.client.get(f"/auth/{harness.guard.issue_ticket()}")
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=strict" in cookie
        assert cookie_name(PORT) in cookie

    def test_forged_cookie_is_rejected(self, harness: Harness) -> None:
        harness.client.cookies.set(cookie_name(PORT), "falso")
        assert harness.client.get("/api/status").status_code == 401

    def test_session_gives_access(self, harness: Harness) -> None:
        harness.login()
        response = harness.client.get("/api/session")
        assert response.json()["csrfToken"] == harness.guard.csrf_token


class TestOriginAndHost:
    @pytest.mark.parametrize(
        "host",
        ["evil.example", "evil.example:54321", "localhost:54321", "127.0.0.1", "127.0.0.1:1"],
    )
    def test_dns_rebinding_is_rejected(self, harness: Harness, host: str) -> None:
        harness.login()
        response = harness.client.get("/api/status", headers={"Host": host})
        assert response.status_code == 403
        assert response.json()["error"] == "invalid_host"

    def test_health_also_validates_host(self, harness: Harness) -> None:
        assert harness.client.get("/health", headers={"Host": "evil.example"}).status_code == 403

    @pytest.mark.parametrize(
        "origin", ["https://evil.example", "http://127.0.0.1:1", "http://localhost:54321", "null"]
    )
    def test_foreign_origin_is_rejected_even_with_valid_tokens(
        self, harness: Harness, origin: str
    ) -> None:
        harness.login()
        response = harness.post("/api/scans", headers={"Origin": origin})
        assert response.status_code == 403
        assert response.json()["error"] == "invalid_origin"

    def test_foreign_origin_cannot_read(self, harness: Harness) -> None:
        harness.login()
        response = harness.client.get("/api/session", headers={"Origin": "https://evil.example"})
        assert response.status_code == 403

    @pytest.mark.parametrize("site", ["cross-site", "same-site"])
    def test_cross_site_fetch_metadata_is_rejected(self, harness: Harness, site: str) -> None:
        harness.login()
        response = harness.client.get("/api/status", headers={"Sec-Fetch-Site": site})
        assert response.status_code == 403

    def test_no_cors_headers_are_ever_sent(self, harness: Harness) -> None:
        harness.login()
        response = harness.client.get("/api/status", headers={"Origin": ORIGIN})
        assert "access-control-allow-origin" not in response.headers

    def test_preflight_is_not_honoured(self, harness: Harness) -> None:
        harness.login()
        response = harness.client.options(
            "/api/scans",
            headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
        )
        assert response.status_code == 403


class TestCsrf:
    def test_post_without_token_is_rejected(self, harness: Harness) -> None:
        harness.login()
        response = harness.client.post("/api/scans", headers={"Origin": ORIGIN})
        assert response.status_code == 403
        assert response.json()["error"] == "invalid_csrf_token"

    def test_post_with_wrong_token_is_rejected(self, harness: Harness) -> None:
        harness.login()
        response = harness.client.post(
            "/api/scans", headers={"Origin": ORIGIN, CSRF_HEADER: "falso"}
        )
        assert response.status_code == 403

    def test_post_without_origin_is_rejected(self, harness: Harness) -> None:
        harness.login()
        response = harness.client.post(
            "/api/scans", headers={CSRF_HEADER: harness.guard.csrf_token}
        )
        assert response.status_code == 403
        assert response.json()["error"] == "origin_required"

    def test_exit_requires_csrf(self, harness: Harness) -> None:
        harness.login()
        assert harness.client.post("/api/exit", headers={"Origin": ORIGIN}).status_code == 403
        assert harness.exit_requests == 0
        assert harness.post("/api/exit").status_code == 202
        assert harness.exit_requests == 1

    def test_form_post_is_rejected(self, harness: Harness) -> None:
        harness.login()
        response = harness.post(
            "/api/pending/export",
            content=b"directory=C:\\",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert response.status_code == 415

    def test_oversized_body_is_rejected(self, harness: Harness) -> None:
        harness.login()
        response = harness.post(
            "/api/pending/export",
            content=b"x" * (70 * 1024),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413


class TestNoCommandSurface:
    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("POST", "/api/run"),
            ("POST", "/api/exec"),
            ("POST", "/api/command"),
            ("GET", "/docs"),
            ("GET", "/openapi.json"),
            ("GET", "/redoc"),
        ],
    )
    def test_routes_do_not_exist(self, harness: Harness, method: str, path: str) -> None:
        harness.login()
        headers = {CSRF_HEADER: harness.guard.csrf_token, "Origin": ORIGIN}
        assert harness.client.request(method, path, headers=headers).status_code == 404

    def test_invalid_json_is_rejected(self, harness: Harness) -> None:
        harness.login()
        response = harness.post(
            "/api/pending/export",
            content=b"{no es json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_scan_rejects_arbitrary_parameters(self, harness: Harness) -> None:
        """El cuerpo se ignora: no hay forma de pasar consultas o comandos a un análisis."""
        harness.login()
        response = harness.post("/api/scans", json={"command": "calc.exe", "queries": ["x"]})
        assert response.status_code == 202
        assert harness.service.scans.wait(30)

    def test_export_rejects_extra_fields(self, harness: Harness) -> None:
        harness.login()
        response = harness.post(
            "/api/pending/export", json={"directory": "C:\\", "fileName": "..\\evil.json"}
        )
        assert response.status_code == 422


class TestInventoryEndpoints:
    def test_scan_history_detail_download(self, harness: Harness) -> None:
        harness.login()
        harness.scan()
        items = harness.client.get("/api/inventories").json()
        assert len(items) == 1
        identifier = items[0]["id"]
        detail = harness.client.get(f"/api/inventories/{identifier}")
        assert detail.status_code == 200
        assert detail.json()["device"]["manufacturer"]["value"] == "HP"
        file_response = harness.client.get(f"/api/inventories/{identifier}/download")
        assert file_response.status_code == 200
        assert "attachment" in file_response.headers["content-disposition"]
        assert harness.post("/api/scans/current/cancel").json() == {"cancelled": False}

    def test_second_concurrent_scan_conflicts(self, harness: Harness) -> None:
        harness.login()
        harness.service.scans.start()
        response = harness.post("/api/scans")
        assert response.status_code in (202, 409)
        assert harness.service.scans.wait(30)

    @pytest.mark.parametrize(
        "bad",
        [
            "otro",
            "honey-check_..%5C..%5Csecreto",
            "honey-check_a%2F..%2Fb",
            "honey-check_%00",
            "secreto.json",
        ],
    )
    def test_traversal_is_rejected(self, harness: Harness, bad: str) -> None:
        harness.login()
        response = harness.client.get(f"/api/inventories/{bad}")
        assert response.status_code in (400, 404)
        response = harness.client.get(f"/api/inventories/{bad}/download")
        assert response.status_code in (400, 404)

    def test_unknown_inventory(self, harness: Harness) -> None:
        harness.login()
        missing = "/api/inventories/00000000-0000-4000-8000-000000000000"
        assert harness.client.get(missing).status_code == 404

    def test_corrupt_inventory_is_a_conflict_not_a_crash(self, harness: Harness) -> None:
        harness.login()
        folder = harness.directory / "HoneyCheck-datos" / "equipos" / "abc" / "inventarios"
        folder.mkdir(parents=True)
        (folder / "v0001_20261105T100000Z.json").write_text("{", encoding="utf-8")
        broken = harness.client.get("/api/inventories").json()[0]
        assert broken["invalidReason"] == "invalid_json"
        response = harness.client.get(f"/api/inventories/{broken['id']}")
        assert response.status_code == 409
        assert response.json()["reason"] == "invalid_json"

    def test_comparison(self, harness: Harness) -> None:
        harness.login()
        harness.scan()
        harness.scan()
        ids = [item["id"] for item in harness.client.get("/api/inventories").json()]
        response = harness.client.get("/api/comparison", params={"base": ids[0], "target": ids[1]})
        assert response.status_code == 200
        assert response.json()["sameDevice"] is True

    def test_only_listed_static_files_are_served(self, harness: Harness) -> None:
        harness.login()
        for path in ("/assets/../app.py", "/assets/secret", "/assets/%2e%2e/app.py"):
            assert harness.client.get(path).status_code == 404


class TestWorkspaceFailure:
    def test_failed_export_offers_alternative_through_api(self, tmp_path: Path) -> None:
        usb = tmp_path / "usb"
        usb.write_text("no es una carpeta", encoding="utf-8")
        other = tmp_path / "otra"
        other.mkdir()
        harness = Harness(usb)
        harness.login()
        harness.scan()
        status = harness.client.get("/api/status").json()
        assert status["workspace"]["writable"] is False
        assert status["exportFailure"] is not None
        pending = harness.client.get("/api/pending")
        assert pending.status_code == 200
        download = harness.client.get("/api/pending/download")
        assert "attachment" in download.headers["content-disposition"]
        rejected = harness.post("/api/pending/export", json={"directory": "\\\\red\\carpeta"})
        assert rejected.status_code == 400
        assert rejected.json()["reason"] == "network_path_not_allowed"
        saved = harness.post("/api/pending/export", json={"directory": str(other)})
        assert saved.status_code == 200
        assert list((other / "HoneyCheck-datos").rglob("v*.json"))
        assert harness.client.get("/api/status").json()["exportFailure"] is None

    def test_open_folder_without_path_opens_the_data_folder(self, harness: Harness) -> None:
        harness.login()
        assert harness.post("/api/folder/open").status_code == 204
        assert harness.opened == [harness.directory / "HoneyCheck-datos"]

    def test_open_folder_accepts_only_folders_inside_the_data_folder(
        self, harness: Harness
    ) -> None:
        harness.login()
        harness.scan()
        inside = harness.client.get("/api/inventories").json()[0]["directory"]
        assert harness.post("/api/folder/open", json={"path": inside}).status_code == 204
        assert harness.opened == [Path(inside).resolve()]
        outside = harness.directory / "fuera"
        outside.mkdir()
        for path in (str(outside), "C:\\Windows", f"{inside}\\..\\..\\..\\..\\fuera"):
            response = harness.post("/api/folder/open", json={"path": path})
            assert response.status_code == 403, path
        assert harness.post("/api/folder/open", json={"directory": "x"}).status_code == 422
        assert len(harness.opened) == 1


class TestDeleteToTrash:
    def test_deleting_a_version_moves_it_to_the_trash(self, harness: Harness) -> None:
        harness.login()
        harness.scan()
        harness.scan()
        newest, oldest = harness.client.get("/api/inventories").json()
        assert harness.post("/api/reference", json={"inventoryId": oldest["id"]}).status_code == 200
        response = harness.post(f"/api/inventories/{oldest['id']}/delete")
        assert response.status_code == 200
        trash = Path(response.json()["trash"])
        assert trash.is_relative_to(harness.directory / "HoneyCheck-datos" / "papelera")
        assert (trash / oldest["fileName"]).is_file()
        remaining = harness.client.get("/api/inventories").json()
        assert [item["id"] for item in remaining] == [newest["id"]]
        assert harness.client.get("/api/status").json()["referenceId"] is None
        assert harness.client.get(f"/api/inventories/{oldest['id']}").status_code == 404

    def test_deleting_a_device_moves_its_folder(self, harness: Harness) -> None:
        harness.login()
        harness.scan()
        harness.scan()
        key = harness.client.get("/api/inventories").json()[0]["deviceKey"]
        response = harness.post(f"/api/devices/{key}/delete")
        assert response.status_code == 200
        assert response.json()["deleted"] == 2
        assert len(list(Path(response.json()["trash"]).rglob("v*.json"))) == 2
        assert harness.client.get("/api/devices").json()["total"] == 0
        assert harness.post(f"/api/devices/{key}/delete").status_code == 404
        assert harness.post("/api/devices/..%2Fx/delete").status_code in {400, 404}

    def test_delete_requires_csrf(self, harness: Harness) -> None:
        harness.login()
        harness.scan()
        item = harness.client.get("/api/inventories").json()[0]
        response = harness.client.post(f"/api/inventories/{item['id']}/delete")
        assert response.status_code == 403
        assert len(harness.client.get("/api/inventories").json()) == 1

    def test_summary_of_a_version(self, harness: Harness) -> None:
        harness.login()
        harness.scan()
        item = harness.client.get("/api/inventories").json()[0]
        summary = harness.client.get(f"/api/inventories/{item['id']}/summary").json()
        assert summary["deviceKey"] == item["deviceKey"]
        assert summary["sequence"] == 1


class TestElevation:
    def test_status_reports_elevation(self, tmp_path: Path) -> None:
        harness = Harness(tmp_path, elevated=True)
        harness.login()
        assert harness.client.get("/api/status").json()["isElevated"] is True
        assert harness.post("/api/elevate").status_code == 409
        assert harness.elevations == 0

    def test_elevate_relaunches_once_accepted(self, harness: Harness) -> None:
        harness.login()
        assert harness.post("/api/elevate").status_code == 202
        assert harness.elevations == 1

    def test_cancelled_prompt_keeps_running(self, harness: Harness) -> None:
        harness.login()
        harness.accept_elevation = False
        response = harness.post("/api/elevate")
        assert response.status_code == 409
        assert response.json()["error"] == "elevation_cancelled"
        assert harness.exit_requests == 0


class TestFolderFailure:
    def test_missing_folder_is_reported_not_a_server_error(self, tmp_path: Path) -> None:
        harness = Harness(tmp_path)

        def fail(_: Path) -> None:
            raise FileNotFoundError("carpeta retirada")

        harness.opened.append = fail  # type: ignore[method-assign]
        harness.login()
        response = harness.post("/api/folder/open")
        assert response.status_code == 409
        assert response.json()["error"] == "folder_unavailable"


class TestResponseHeaders:
    def test_csp_and_friends(self, harness: Harness) -> None:
        for path in ("/health", "/api/status"):
            response = harness.client.get(path)
            csp = response.headers["content-security-policy"]
            assert "default-src 'none'" in csp
            assert "unsafe-inline" not in csp
            assert "frame-ancestors 'none'" in csp
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["cache-control"] == "no-store"
            assert "server" not in response.headers


class TestPathPicker:
    def test_dialog_path_comes_back_only_with_a_session(self, harness: Harness) -> None:
        assert harness.post("/api/pick", json={"kind": "folder"}).status_code in (401, 403)
        harness.login()
        response = harness.post("/api/pick", json={"kind": "folder", "title": "Controladores"})
        assert response.json() == {"path": r"D:\Elegida\folder-Controladores"}
        assert harness.post("/api/pick", json={"kind": "programa"}).status_code == 422

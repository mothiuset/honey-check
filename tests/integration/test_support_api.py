"""API de soporte detrás de la misma sesión y protección CSRF que el resto de la aplicación."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from starlette.testclient import TestClient
from test_http_security import ORIGIN, PORT, Harness

from honey_check.application.support.engine import SupportEngine
from honey_check.application.support.ports import SupportEnvironment
from honey_check.application.support.procedures import ProcedureService
from honey_check.domain.support import Risk, ToolResult
from honey_check.infrastructure.device_store import InventoryNotFound, InventoryUnreadable
from honey_check.infrastructure.support.base import SupportTool, check, fact, step, text, tool
from honey_check.infrastructure.support.journal import FileRunJournal
from honey_check.infrastructure.support.procedure_store import FileProcedureStore
from honey_check.presentation.http.app import AppCallbacks, create_app
from honey_check.presentation.http.security import CSRF_HEADER, SessionGuard

CHANGES: list[str] = []

TOOLS = [
    SupportTool(
        tool(
            "demo.read",
            "Pruebas",
            "Leer",
            "Lectura",
            Risk.READ,
            params=[text("name", "Nombre", pattern=r"[A-Z-]+")],
        ),
        lambda p, _e: [step(f"Leer {p['name']}", "hostname")],
        lambda p, _c: ToolResult(summary=[fact("Nombre", p["name"])]),
    ),
    SupportTool(
        tool("demo.change", "Pruebas", "Cambiar", "Cambio", Risk.DESTRUCTIVE),
        lambda _p, _e: [step("Eliminar algo ficticio")],
        lambda _p, _c: (
            CHANGES.append("hecho") or ToolResult(checks=[check("Hecho", True)], verified=True)
        ),  # type: ignore[func-returns-value]
    ),
]


class SupportHarness(Harness):
    def __init__(self, directory: Path) -> None:
        super().__init__(directory)
        data = directory / "HoneyCheck-datos"
        self.engine = SupportEngine(
            TOOLS,
            FileRunJournal(lambda: data),
            lambda: SupportEnvironment(data, None, False, None),  # type: ignore[arg-type]
        )
        self.procedures = ProcedureService(FileProcedureStore(lambda: data))
        self.guard = SessionGuard()
        app = create_app(
            self.service,
            self.guard,
            lambda: PORT,
            "0.1.0",
            AppCallbacks(lambda _p: None, lambda: None, lambda: False, lambda: False),
            (InventoryNotFound, InventoryUnreadable),
            support=(self.engine, self.procedures),
        )
        self.client = TestClient(app, base_url=ORIGIN, follow_redirects=False)

    def wait(self, run_id: str) -> dict[str, Any]:
        for _ in range(200):
            body = self.client.get(f"/api/support/runs/{run_id}").json()
            if body["status"] != "running":
                return body
            time.sleep(0.02)
        raise AssertionError("no terminó")


@pytest.fixture
def support(tmp_path: Path) -> SupportHarness:
    CHANGES.clear()
    harness = SupportHarness(tmp_path)
    harness.login()
    yield harness
    harness.engine.shutdown()


@pytest.mark.parametrize("path", ["/api/support/tools", "/api/support/runs", "/api/procedures"])
def test_support_requires_session(tmp_path: Path, path: str) -> None:
    assert SupportHarness(tmp_path).client.get(path).status_code == 401


def test_plan_requires_csrf(support: SupportHarness) -> None:
    response = support.client.post(
        "/api/support/plans", json={"tool": "demo.read"}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 403
    response = support.client.post(
        "/api/support/plans",
        json={"tool": "demo.read"},
        headers={CSRF_HEADER: support.guard.csrf_token, "Origin": "http://evil.example"},
    )
    assert response.status_code == 403


def test_read_flow(support: SupportHarness) -> None:
    catalog = support.client.get("/api/support/tools").json()
    assert {t["id"] for t in catalog} == {"demo.read", "demo.change"}
    plan = support.post(
        "/api/support/plans", json={"tool": "demo.read", "params": {"name": "EQUIPO-FICTICIO"}}
    ).json()
    assert plan["steps"][0]["command"] == "hostname"
    started = support.post("/api/support/runs", json={"planId": plan["id"]})
    assert started.status_code == 202
    run = support.wait(started.json()["id"])
    assert run["status"] == "succeeded"
    assert run["result"]["summary"][0]["value"] == "EQUIPO-FICTICIO"
    history = support.client.get("/api/support/runs").json()
    # Versiones livianas: el resumen sí (para listarlas), tablas y gráficos no.
    assert history[0]["id"] == run["id"]
    assert history[0]["result"]["summary"] and history[0]["result"]["tables"] == []
    only_this = support.client.get("/api/support/runs", params={"tool": "demo.read"}).json()
    assert {item["tool"] for item in only_this} == {"demo.read"}


def test_destructive_change_needs_explicit_confirmation(support: SupportHarness) -> None:
    plan = support.post("/api/support/plans", json={"tool": "demo.change"}).json()
    refused = support.post("/api/support/runs", json={"planId": plan["id"]})
    assert (refused.status_code, refused.json()["error"]) == (409, "confirmation_required")
    assert CHANGES == []
    started = support.post("/api/support/runs", json={"planId": plan["id"], "confirmed": True})
    assert support.wait(started.json()["id"])["status"] == "succeeded"
    assert CHANGES == ["hecho"]
    again = support.post("/api/support/runs", json={"planId": plan["id"], "confirmed": True})
    assert (again.status_code, again.json()["error"]) == (409, "plan_expired")


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"tool": "demo.read", "params": {"name": "minúsculas"}}, "invalid_params"),
        ({"tool": "demo.read", "params": {"cmd": "calc.exe"}}, "invalid_params"),
        ({"tool": "demo.nada"}, "unknown_tool"),
        ({"tool": "demo.read", "extra": 1}, "invalid_request"),
    ],
)
def test_bad_plans_are_refused(support: SupportHarness, body: dict[str, Any], code: str) -> None:
    response = support.post("/api/support/plans", json=body)
    assert response.status_code in (404, 422)
    assert response.json()["error"] == code


def test_procedures_api(support: SupportHarness) -> None:
    slugs = {p["slug"] for p in support.client.get("/api/procedures").json()}
    assert "firma-digital" in slugs
    saved = support.post(
        "/api/procedures",
        json={
            "slug": "puesto-ficticio",
            "name": "Puesto ficticio",
            "steps": [{"id": "a", "kind": "manual", "title": "Revisar"}],
        },
    )
    assert saved.status_code == 201 and saved.json()["version"] == 1
    assert support.client.get("/api/procedures/puesto-ficticio").json()[0]["version"] == 1
    assert (
        support.post("/api/procedures", json={"slug": "x", "name": "", "steps": []}).status_code
        == 422
    )
    assert support.client.get("/api/procedures/no-existe").status_code == 404

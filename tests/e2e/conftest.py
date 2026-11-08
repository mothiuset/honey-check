"""Navegador real (Edge o Chrome del equipo) y servidor de la interfaz con datos ficticios."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, sync_playwright
from ui_server import UiServer, start_ui_server


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        for channel in ("msedge", "chrome"):
            try:
                instance = playwright.chromium.launch(channel=channel, headless=True)
            except Exception:  # noqa: S112 - se prueba el siguiente navegador
                continue
            yield instance
            instance.close()
            return
        pytest.skip("No hay Edge ni Chrome instalados")


@pytest.fixture
def ui(tmp_path: Path) -> Iterator[UiServer]:
    server = start_ui_server(tmp_path)
    yield server
    server.stop()


@pytest.fixture
def page(browser: Browser, ui: UiServer) -> Iterator[Page]:
    context = browser.new_context(viewport={"width": 1366, "height": 860}, accept_downloads=True)
    instance = context.new_page()
    instance.goto(ui.entry_url())
    yield instance
    context.close()

"""Interfaz en un navegador real (Edge o Chrome del equipo) con análisis simulado."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect
from ui_server import HOSTILE_NAME, UiServer, other_device_ports, scan_into, start_ui_server

pytestmark = pytest.mark.e2e

SCREENSHOTS = os.environ.get("HONEY_CHECK_SCREENSHOTS")


def shot(page: Page, name: str) -> None:
    if SCREENSHOTS:
        page.screenshot(path=str(Path(SCREENSHOTS) / f"{name}.png"), full_page=True)


def open_view(page: Page, label: str) -> None:
    """Abre una vista desde el menú: las secciones con apartados se despliegan antes de navegar."""
    nav = page.get_by_role("navigation", name="Secciones")
    parent = nav.get_by_role("button", name=label, exact=True)
    if parent.count():
        if parent.get_attribute("aria-expanded") != "true":
            parent.click()
        nav.get_by_role("list", name=f"Apartados de {label}").get_by_role("link").first.click()
    else:
        nav.get_by_role("link", name=label, exact=True).click()


def analyze(page: Page) -> None:
    page.get_by_role("button", name="Analizar equipo").or_(
        page.get_by_role("button", name="Actualizar análisis")
    ).click()
    expect(page.locator('[data-part="plate-name"]')).to_have_text("PC-FICTICIO-01", timeout=30000)


class TestFlow:
    def test_entry_url_is_removed_from_the_address_bar(self, page: Page) -> None:
        assert "/auth/" not in page.url

    def test_first_screen_invites_to_analyze(self, page: Page) -> None:
        expect(page.get_by_role("button", name="Analizar equipo")).to_be_visible()
        shot(page, "01-inicio")

    def test_full_scan_and_every_section(self, page: Page, ui: UiServer) -> None:
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "console",
            lambda message: errors.append(message.text) if message.type == "error" else None,
        )
        analyze(page)
        expect(page.locator('[data-part="plate-sub"]')).to_have_text("HP ProBook Ficticio 400")
        expect(page.get_by_text("Guardado como versión 1 de este equipo")).to_be_visible()
        assert list(ui.directory.rglob("v0001_*.json"))
        shot(page, "02-panel")

        for name, heading, check in [
            ("Hardware", "Hardware", "ProBook Ficticio 400"),
            ("Almacenamiento", "Almacenamiento", "SSD SATA"),
            ("Software", "Software", "Editor Ficticio"),
            ("Sistema", "Sistema", "Microsoft Windows 11 Enterprise"),
            ("Seguridad", "Seguridad", "Arranque seguro"),
            ("Carpeta de datos", "Carpeta de datos", "Cómo se organiza"),
            ("Equipos y versiones", "Equipos y versiones", "PC-FICTICIO-01"),
        ]:
            open_view(page, name)
            expect(page.locator("main h1")).to_have_text(heading)
            expect(page.locator("main").get_by_text(check).first).to_be_visible()
            shot(page, f"03-{name.lower()}")
        assert errors == []

    def test_cell_of_the_comb_opens_its_section(self, page: Page) -> None:
        analyze(page)
        page.get_by_role("link", name="Software: completo").click()
        expect(page.locator("main h1")).to_have_text("Software")

    def test_exit_button(self, page: Page, ui: UiServer) -> None:
        page.get_by_role("button", name="Salir de Honey Check").click()
        expect(page.get_by_text("Honey Check se cerró")).to_be_visible()
        assert ui.exit_requests == [1]


class TestSoftwareView:
    def test_untrusted_names_are_text_not_html(self, page: Page) -> None:
        analyze(page)
        open_view(page, "Software")
        expect(page.get_by_role("button", name=HOSTILE_NAME)).to_be_visible()
        assert page.evaluate("window.__xss") is None
        assert page.locator("main table img").count() == 0

    def test_search_and_details(self, page: Page) -> None:
        analyze(page)
        open_view(page, "Software")
        page.get_by_role("searchbox").fill("editorial")
        expect(page.get_by_role("button", name="Visor Antiguo")).to_have_count(0)
        page.get_by_role("button", name="Editor Ficticio").click()
        detail = page.locator("tr[data-detail]")
        expect(detail.get_by_text("no se ejecuta")).to_be_visible()
        expect(detail.get_by_text("Firma válida")).to_be_visible()
        shot(page, "04-software-detalle")

    def test_system_components_are_hidden_by_default(self, page: Page) -> None:
        analyze(page)
        open_view(page, "Software")
        expect(page.get_by_role("button", name="Componente interno")).to_have_count(0)
        page.get_by_role("checkbox").check()
        expect(page.get_by_role("button", name="Componente interno")).to_be_visible()


class TestPeripheralsView:
    def test_one_row_per_device_and_what_is_no_longer_connected(self, page: Page) -> None:
        analyze(page)
        page.evaluate("location.hash = '#perifericos'")
        main = page.get_by_role("main")
        # Nueve nodos de Windows son un solo teclado, con lo que hace.
        expect(main.get_by_text("Teclado Ficticio K1", exact=True)).to_have_count(1)
        expect(main.get_by_text("teclado, mouse, teclas multimedia")).to_be_visible()
        expect(main.get_by_text("Touchpad integrado", exact=True)).to_be_visible()
        expect(main.get_by_text("Pantalla Ficticia 27", exact=True)).to_be_visible()
        paired = main.get_by_role("region", name="Emparejados por Bluetooth (1)")
        expect(paired.get_by_text("Audífonos Ficticios")).to_be_visible()
        gone = main.get_by_role("region", name="Ya no están (1)")
        expect(gone.get_by_text("conectado ahora en otro puerto")).to_be_visible()
        shot(page, "06-perifericos")
        # Quitar abre su revisión en el panel, sin salir de la vista.
        gone.get_by_role("button", name="Quitar").click()
        panel = page.get_by_test_id("action-panel")
        expect(panel.get_by_role("heading", name="Quitar aparatos que ya no están")).to_be_visible()
        expect(page).to_have_url(re.compile("#perifericos"))


class TestStorageView:
    def test_units_have_their_letter_and_actions(self, page: Page) -> None:
        analyze(page)
        page.evaluate("location.hash = '#almacenamiento'")
        main = page.get_by_role("main")
        expect(main.get_by_text("C:", exact=True)).to_be_visible()
        expect(main.get_by_text("80 GiB libres de 200 GiB")).to_be_visible()
        expect(main.get_by_role("link", name="Analizar espacio")).to_be_visible()
        reserved = main.get_by_text("1 partición que Windows reserva (sin letra)")
        expect(reserved).to_be_visible()
        reserved.click()
        expect(main.get_by_text("Arranque (EFI)")).to_be_visible()
        shot(page, "07-almacenamiento")


class TestRegressions:
    def test_date_only_values_do_not_shift_a_day(self, page: Page) -> None:
        """En América, una fecha sola interpretada como UTC mostraba el día anterior."""
        analyze(page)
        open_view(page, "Software")
        page.get_by_role("button", name="Editor Ficticio").click()
        expect(page.locator("tr[data-detail]").get_by_text("15")).to_be_visible()

    def test_partial_cell_uses_hatch_fill(self, page: Page) -> None:
        analyze(page)
        cell = page.locator('[data-cell][data-status="partial"] polygon').first
        assert "partial-hatch" in cell.evaluate("node => getComputedStyle(node).fill")


class TestResponsive:
    def test_no_horizontal_scroll_on_phone(self, browser: Browser, ui: UiServer) -> None:
        context = browser.new_context(viewport={"width": 390, "height": 800})
        page = context.new_page()
        page.goto(ui.entry_url())
        analyze(page)
        width = page.evaluate("document.documentElement.scrollWidth")
        assert width <= 390
        shot(page, "06-movil")
        context.close()

    def test_dark_mode_renders(self, browser: Browser, ui: UiServer) -> None:
        context = browser.new_context(viewport={"width": 1366, "height": 860}, color_scheme="dark")
        page = context.new_page()
        page.goto(ui.entry_url())
        analyze(page)
        shot(page, "07-oscuro")
        context.close()


class TestAccessibility:
    def test_comb_cells_are_keyboard_reachable(self, page: Page) -> None:
        analyze(page)
        cell = page.get_by_role("link", name="Memoria: completo")
        cell.focus()
        page.keyboard.press("Enter")
        expect(page.locator("main h1")).to_have_text("Hardware")


class TestDeepLinks:
    @pytest.mark.parametrize(
        ("cell", "anchor"),
        [("Memoria", "memoria"), ("TPM", "tpm"), ("Red", "red"), ("Dispositivos", "dispositivos")],
    )
    def test_comb_cell_opens_its_exact_section(self, page: Page, cell: str, anchor: str) -> None:
        analyze(page)
        page.get_by_role("link", name=f"{cell}: ").first.click()
        expect(page).to_have_url(re.compile(f"#hardware/{anchor}$"))
        heading = page.locator(f"h2#{anchor}")
        expect(heading).to_be_focused()
        box = heading.bounding_box()
        assert box is not None
        # Los últimos apartados no pueden subir hasta arriba, pero deben quedar a la vista.
        assert 0 <= box["y"] < page.viewport_size["height"] - box["height"]

    def test_same_link_twice_still_scrolls(self, page: Page) -> None:
        analyze(page)
        page.get_by_role("link", name="Memoria: ").first.click()
        page.mouse.wheel(0, 3000)
        open_view(page, "Panel")
        page.get_by_role("link", name="Memoria: ").first.click()
        expect(page.locator("h2#memoria")).to_be_focused()


VIEWS = [
    "panel",
    "hardware",
    "almacenamiento",
    "software",
    "sistema",
    "seguridad",
    "equipos",
    "exportaciones",
    "soporte",
    "soporte?tool=demo.analyze&auto=1",
    "procesos",
    "historial",
]


class TestNoHorizontalOverflow:
    @pytest.mark.parametrize("width", [360, 768, 1024, 1366])
    def test_every_view_fits(self, browser: Browser, ui: UiServer, width: int) -> None:
        context = browser.new_context(viewport={"width": width, "height": 800})
        page = context.new_page()
        page.goto(ui.entry_url())
        analyze(page)
        for view in VIEWS:
            page.evaluate("view => { location.hash = view; }", view)
            page.wait_for_timeout(250)
            overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            assert overflow <= 1, f"{view} desborda {overflow}px a {width}px"
            if width in (360, 1024) and view in ("software", "hardware", "equipos"):
                shot(page, f"09-{view}-{width}")
        context.close()


def test_no_object_placeholders_leak_into_the_page(page: Page) -> None:
    """Regresión: un objeto pasado como contenido aparecía como «[object Object]»."""
    analyze(page)
    for view in VIEWS:
        page.evaluate("view => { location.hash = view; }", view)
        page.wait_for_timeout(200)
        assert "[object Object]" not in page.locator("body").inner_text(), view


class TestGroupedNavigation:
    def test_parent_item_expands_without_navigating(self, page: Page) -> None:
        analyze(page)
        nav = page.get_by_role("navigation", name="Secciones")
        for group in ("Análisis del equipo", "Equipos guardados", "Datos"):
            expect(nav.get_by_text(group, exact=True)).to_be_visible()
        before = page.url
        hardware = nav.get_by_role("button", name="Hardware", exact=True)
        expect(hardware).to_have_attribute("aria-expanded", "false")
        hardware.click()
        expect(hardware).to_have_attribute("aria-expanded", "true")
        assert page.url == before  # Desplegar no navega.
        sub = nav.get_by_role("list", name="Apartados de Hardware")
        expect(sub.get_by_role("link", name="Memoria")).to_be_visible()
        # Se pueden explorar varias secciones a la vez antes de elegir.
        nav.get_by_role("button", name="Sistema", exact=True).click()
        expect(nav.get_by_role("list", name="Apartados de Sistema")).to_be_visible()
        sub.get_by_role("link", name="Memoria").click()
        expect(page.locator("h2#memoria")).to_be_focused()
        hardware.click()
        expect(sub).to_be_hidden()

    def test_first_entry_opens_the_whole_view(self, page: Page) -> None:
        analyze(page)
        open_view(page, "Seguridad")
        expect(page.locator("main h1")).to_have_text("Seguridad")

    def test_top_bar_does_not_cover_the_section_title(self, browser: Browser, ui: UiServer) -> None:
        context = browser.new_context(viewport={"width": 680, "height": 800})
        page = context.new_page()
        page.goto(ui.entry_url())
        analyze(page)
        page.get_by_role("link", name="Memoria: ").first.click()
        heading = page.locator("h2#memoria")
        expect(heading).to_be_focused()
        bar = page.locator('[data-part="rail-bar"]').bounding_box()
        box = heading.bounding_box()
        assert bar is not None and box is not None
        assert box["y"] >= bar["y"] + bar["height"]
        page.get_by_role("button", name="Menú").click()
        expect(page.get_by_role("list", name="Apartados de Hardware")).to_be_visible()
        # En el menú desplegable, desplegar una sección tampoco lo cierra.
        page.get_by_role("button", name="Software", exact=True).click()
        expect(page.get_by_role("list", name="Apartados de Software")).to_be_visible()
        shot(page, "10-menu-estrecho")
        context.close()


class TestTopBarNavigation:
    """En ventanas estrechas la barra es fija: nada a lo que se navega puede quedar debajo."""

    def assert_below_bar(self, page: Page, locator: Any) -> None:
        page.wait_for_timeout(300)
        bar = page.locator('[data-part="rail-bar"]').bounding_box()
        box = locator.bounding_box()
        assert bar is not None and box is not None
        assert box["y"] >= bar["y"] + bar["height"] - 1, (box, bar)
        # Y sin un hueco excesivo encima.
        assert box["y"] <= bar["y"] + bar["height"] + 40, (box, bar)

    @pytest.mark.parametrize("width", [680, 380])
    def test_views_and_subsections_from_the_menu(
        self, browser: Browser, ui: UiServer, width: int
    ) -> None:
        context = browser.new_context(viewport={"width": width, "height": 760})
        page = context.new_page()
        page.goto(ui.entry_url())
        analyze(page)
        menu = page.get_by_role("button", name="Menú")

        # Desde abajo de una vista larga, ir a otra vista desde el menú.
        menu.click()
        open_view(page, "Hardware")
        page.mouse.wheel(0, 2500)
        menu.click()
        open_view(page, "Software")
        self.assert_below_bar(page, page.locator("main h1"))

        # Y un apartado concreto desde el submenú.
        menu.click()
        open_view(page, "Hardware")
        menu.click()
        page.get_by_role("list", name="Apartados de Hardware").get_by_role(
            "link", name="Batería"
        ).click()
        self.assert_below_bar(page, page.locator("h2#bateria"))
        context.close()


def test_expanding_sections_in_the_compact_menu_keeps_it_open(
    browser: Browser, ui: UiServer
) -> None:
    """Regresión: desplegar una sección en el menú de pantallas estrechas lo cerraba."""
    context = browser.new_context(viewport={"width": 680, "height": 800})
    page = context.new_page()
    page.goto(ui.entry_url())
    analyze(page)
    toggle = page.get_by_role("button", name="Menú")
    toggle.click()
    for label in ("Hardware", "Software", "Sistema", "Hardware"):
        page.get_by_role("button", name=label, exact=True).click()
        expect(toggle).to_have_attribute("aria-expanded", "true")
    page.get_by_role("list", name="Apartados de Software").get_by_role(
        "link", name="Fuentes consultadas"
    ).click()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(page.locator("h2#fuentes")).to_be_focused()
    # Un clic fuera del menú sí lo cierra.
    toggle.click()
    # El menú desplegado llega hasta la barra de estado: se pulsa en ella, fuera del menú.
    page.mouse.click(4, 781)
    expect(toggle).to_have_attribute("aria-expanded", "false")
    context.close()


def device_row(page: Page, text: str) -> Any:
    return page.locator("#device-results tbody tr").filter(has_text=text).first


def open_devices(page: Page) -> None:
    open_view(page, "Equipos y versiones")
    expect(page.locator("#device-results tbody tr").first).to_be_visible()


class TestDevicesAndVersions:
    def test_versions_and_comparison(self, page: Page) -> None:
        analyze(page)
        page.get_by_role("button", name="Actualizar análisis").click()
        expect(page.get_by_text("Este equipo tiene 2 análisis guardados")).to_be_visible(
            timeout=30000
        )
        open_devices(page)
        row = device_row(page, "PC-FICTICIO-01")
        expect(row.get_by_text("este equipo", exact=True)).to_be_visible()
        row.get_by_role("button").first.click()
        versions = page.locator("#device-results tr[data-detail] tbody tr")
        expect(versions).to_have_count(2)
        # «Comparar» en una versión la deja como segunda parte de la comparación.
        versions.nth(1).get_by_role("button", name="Comparar").click()
        page.get_by_role("searchbox", name="Base: buscar equipo").fill("ficticio")
        page.locator('[data-part="picker-option"]').first.click()
        page.get_by_role("button", name="Comparar", exact=True).last.click()
        expect(page.get_by_role("heading", name="Resultado de la comparación")).to_be_visible()
        shot(page, "05-comparacion")

    def test_reference_can_be_set(self, page: Page) -> None:
        analyze(page)
        open_devices(page)
        device_row(page, "PC-FICTICIO-01").get_by_role("button").first.click()
        page.get_by_role("button", name="Usar como referencia").click()
        expect(page.get_by_text("referencia", exact=True)).to_be_visible()

    def test_other_devices_are_not_shown_as_this_one(
        self, browser: Browser, tmp_path: Path
    ) -> None:
        scan_into(tmp_path, other_device_ports())
        ui = start_ui_server(tmp_path)
        try:
            context = browser.new_context(viewport={"width": 1366, "height": 860})
            page = context.new_page()
            page.goto(ui.entry_url())
            # El panel no abre el inventario del otro equipo como si fuera este.
            expect(page.locator('[data-part="plate-name"]')).to_have_text("Honey Check")
            expect(page.get_by_text("Este equipo todavía no tiene análisis")).to_be_visible()
            open_devices(page)
            row = device_row(page, "Acer Veriton Ficticio N1")
            row.get_by_role("button").first.click()
            page.locator("#device-results tr[data-detail]").get_by_role(
                "button", name="Ver", exact=True
            ).click()
            expect(page.get_by_text("que no es este equipo")).to_be_visible()
            shot(page, "08-otro-equipo")
            page.get_by_role("button", name="Volver a este equipo").click()
            expect(page.get_by_text("que no es este equipo")).to_have_count(0)
            context.close()
        finally:
            ui.stop()

    def test_search_filter_and_sort(self, browser: Browser, tmp_path: Path) -> None:
        scan_into(tmp_path, other_device_ports())
        ui = start_ui_server(tmp_path)
        try:
            context = browser.new_context(viewport={"width": 1366, "height": 860})
            page = context.new_page()
            page.goto(ui.entry_url())
            analyze(page)
            open_devices(page)
            rows = page.locator("#device-results tbody tr")
            expect(rows).to_have_count(2)
            page.get_by_role("searchbox", name="Buscar equipos").fill("veriton")
            expect(rows).to_have_count(1)
            expect(page.get_by_text("1 equipo", exact=True)).to_be_visible()
            page.get_by_role("searchbox", name="Buscar equipos").fill("")
            expect(rows).to_have_count(2)
            page.get_by_role("combobox", name="Fabricante").select_option("HP")
            expect(rows).to_have_count(1)
            expect(device_row(page, "HP ProBook")).to_be_visible()
            page.get_by_role("combobox", name="Fabricante").select_option("")
            expect(rows).to_have_count(2)
            page.get_by_role("button", name="Fabricante y modelo").click()
            expect(rows.first).to_contain_text("Acer")
            page.get_by_role("button", name="Fabricante y modelo").click()
            expect(rows.first).to_contain_text("HP")
            page.get_by_role("searchbox", name="Buscar equipos").fill("no-existe-nada")
            expect(page.get_by_text("Ningún equipo coincide")).to_be_visible()
            shot(page, "11-equipos-busqueda")
            context.close()
        finally:
            ui.stop()

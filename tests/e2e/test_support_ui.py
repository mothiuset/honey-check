"""Soporte en un navegador real, con herramientas ficticias que no tocan el equipo."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest
import support_demo
from playwright.sync_api import Page, expect
from support_demo import HOSTILE_FOLDER, REMOVED
from test_ui import open_view, shot

from simulated_windows import (
    SimulatedDomain,
    SimulatedNetwork,
    SimulatedPrinter,
    SimulatedRepair,
    SimulatedUpdates,
)

pytestmark = pytest.mark.e2e


def go(page: Page, hash_: str) -> None:
    page.evaluate("h => { location.hash = h }", hash_)


def test_catalog_groups_tools_and_hides_internal_ones(page: Page) -> None:
    open_view(page, "Herramientas")
    expect(page.get_by_role("heading", name="Soporte", level=1)).to_be_visible()
    expect(page.locator("[data-tool]")).to_have_count(9)
    expect(page.locator('[data-tool="demo.remove"]')).to_have_count(0)
    page.locator('[data-tool="demo.analyze"]').click()
    expect(page.get_by_role("heading", name="Analizar espacio (ficticio)")).to_be_visible()


def test_read_tool_runs_and_shows_space_table_and_fix(page: Page) -> None:
    go(page, "#soporte?tool=demo.analyze")
    page.get_by_role("button", name="Consultar").click()
    space = page.get_by_role("region", name="Mapa de carpetas")
    expect(space.locator("ul > li")).to_have_count(3, timeout=10000)
    expect(space.get_by_text("Videos")).to_be_visible()
    # Un nombre hostil se muestra como texto, nunca como HTML.
    expect(space.get_by_text(HOSTILE_FOLDER)).to_be_visible()
    expect(page.locator('[data-table="archivos"] tbody tr')).to_have_count(15)
    page.get_by_label("Buscar en la tabla").fill("grabacion-1")
    expect(page.locator('[data-table="archivos"] tbody tr')).to_have_count(6)
    assert page.evaluate("window.__xss || null") is None
    shot(page, "20-soporte-analisis")
    # La corrección propuesta abre su revisión en el panel, sin salir del análisis.
    page.locator('[data-action="demo.cleanup"]').click()
    panel = page.get_by_test_id("action-panel")
    expect(panel.get_by_role("heading", name="Limpiar temporales (ficticio)")).to_be_visible()
    expect(page.get_by_role("heading", name="Analizar espacio (ficticio)", level=1)).to_be_visible()
    panel.get_by_role("button", name="Cerrar").click()
    expect(panel).to_have_count(0)


def test_change_is_reviewed_and_done_in_one_screen(page: Page) -> None:
    go(page, "#soporte?tool=demo.cleanup")
    page.get_by_role("button", name="Revisar antes de hacerlo").click()
    panel = page.get_by_role("region", name="Se ejecutará «Limpiar temporales (ficticio)».")
    expect(panel.get_by_text("Cierre los programas abiertos.")).to_be_visible()
    expect(panel.get_by_text("Respaldo: Los archivos van a la Papelera")).to_be_visible()
    panel.get_by_text("Ver los pasos y comandos").click()
    expect(panel.get_by_text(r"del /q %TEMP%\*")).to_be_visible()
    # Cambiar una opción vuelve a revisar sin otro botón.
    page.get_by_label("Alcance").select_option("all")
    expect(panel).to_be_visible()
    shot(page, "21-soporte-revision")
    # Sin segundo diálogo: el botón del panel es la confirmación.
    panel.get_by_role("button", name="Limpiar temporales (ficticio)").click()
    expect(page.get_by_text("Hecho y verificado.")).to_be_visible(timeout=10000)
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.get_by_text("Liberados 12 MB")).to_be_visible()


def test_bulk_selection_arrives_reviewed_at_the_destructive_tool(page: Page) -> None:
    REMOVED.clear()
    go(page, "#soporte?tool=demo.analyze&auto=1")
    table = page.locator('[data-table="archivos"]')
    expect(table.locator("tbody tr")).to_have_count(15, timeout=10000)
    table.get_by_label(re.compile(r"Elegir .*grabacion-0\.mp4")).check()
    table.get_by_label(re.compile(r"Elegir .*grabacion-3\.mp4")).check()
    table.locator('[data-action="demo.remove"]').click()
    # La revisión se abre en el panel, sobre el análisis: no hay otra página ni otro diálogo.
    panel = page.get_by_test_id("action-panel")
    expect(panel.get_by_role("heading", name="Enviar a la Papelera")).to_be_visible()
    expect(page).to_have_url(re.compile(r"tool=demo\.analyze"))
    panel.get_by_role("button", name="Enviar a la Papelera").click()
    expect(panel.get_by_text("Hecho: 2 de 2, verificados.")).to_be_visible(timeout=10000)
    shot(page, "32-panel-de-accion")
    panel.get_by_role("button", name="Listo").click()
    expect(table).to_be_visible()
    # El análisis de atrás ya no refleja el equipo: lo dice y ofrece actualizarlo.
    expect(
        page.get_by_text(re.compile(r"^El equipo cambió después de este resultado"))
    ).to_be_visible()
    assert [sorted(p.rsplit("\\", 1)[1] for p in REMOVED[0])] == [
        ["grabacion-0.mp4", "grabacion-3.mp4"]
    ]


def test_admin_action_asks_windows_only_for_itself(page: Page) -> None:
    go(page, "#soporte?tool=demo.admin")
    page.get_by_role("button", name="Revisar antes de hacerlo").click()
    expect(
        page.get_by_text("Windows pedirá permiso de administrador solo para esta acción.")
    ).to_be_visible()
    page.get_by_role("button", name="Reparar sistema (ficticio)").click()
    expect(page.get_by_text("Hecho y verificado.")).to_be_visible(timeout=10000)
    expect(page.get_by_text(re.compile(r"duró .*, como administrador"))).to_be_visible()


def test_long_run_can_be_cancelled_and_appears_in_history(page: Page) -> None:
    go(page, "#soporte?tool=demo.slow")
    page.get_by_role("button", name="Revisar antes de hacerlo").click()
    page.get_by_role("button", name="Tarea larga (ficticia)").click()
    page.get_by_role("button", name="Cancelar").click()
    expect(page.get_by_text("Se canceló. Lo hecho hasta ahí quedó en el registro.")).to_be_visible(
        timeout=10000
    )
    open_view(page, "Historial")
    row = page.locator("tbody tr").filter(has_text="Tarea larga (ficticia)")
    expect(row).to_contain_text("Cancelado")
    row.get_by_role("link").click()
    expect(page.get_by_role("heading", name="Tarea larga (ficticia)")).to_be_visible()
    expect(page.get_by_text("Cancelado por el técnico")).to_be_attached()


def test_procedures_list_templates_and_save_a_version(page: Page) -> None:
    open_view(page, "Procesos de instalación")
    for name in ("Equipo recién formateado", "Paquete de oficina", "Firma digital (token)"):
        expect(page.get_by_role("heading", name=name)).to_be_visible()
    page.get_by_role("button", name="Nuevo proceso").click()
    page.get_by_role("button", name="Guardar versión").click()
    expect(page.get_by_text("Guardado «Mi proceso» como versión 1.")).to_be_visible()
    card = page.locator('[data-procedure="mi-proceso"]')
    expect(card.get_by_text("Versión 1")).to_be_visible()
    card.get_by_role("button", name="Editar").click()
    editor = page.get_by_label("Definición del proceso en JSON")
    editor.fill(editor.input_value().replace('"Mi proceso"', '"Mi proceso v2"'))
    page.get_by_role("button", name="Guardar versión").click()
    expect(page.get_by_text("como versión 2.")).to_be_visible()
    page.get_by_role("button", name="Nuevo proceso").click()
    page.get_by_label("Definición del proceso en JSON").fill("{ no es json")
    page.get_by_role("button", name="Guardar versión").click()
    expect(page.get_by_text("no es JSON válido")).to_be_visible()


def test_printer_and_program_rows_link_to_support(page: Page) -> None:
    page.get_by_role("button", name="Analizar equipo").click()
    expect(page.locator('[data-part="plate-name"]')).to_have_text("PC-FICTICIO-01", timeout=30000)
    go(page, "#software")
    page.locator("tbody tr").filter(has_text="Editor Ficticio").locator("button").first.click()
    expect(page.get_by_role("link", name="Desinstalar")).to_have_attribute(
        "href", re.compile(r"#soporte\?tool=software\.uninstall&software=[0-9a-f]{16}")
    )


@pytest.fixture
def broken_domain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[SimulatedDomain]:
    """Dominio simulado con la hora desfasada y Registry.pol dañado (ver simulated_windows.py)."""
    windows = SimulatedDomain(
        tmp_path / "Windows", clock_offset_s=9 * 60, machine_pol=b"\x00basura"
    ).install(monkeypatch)
    support_demo.SIMULATED.append(windows)
    yield windows
    support_demo.SIMULATED.clear()


def test_policies_solver_shows_the_causes_and_fixes_them(
    page: Page, broken_domain: SimulatedDomain
) -> None:
    go(page, "#soporte?tool=domain.policies&target=computer&auto=1")
    panel = page.get_by_role("region", name=re.compile(r"^Se corregirá hora desfasada"))
    expect(panel.get_by_text("Hora desfasada", exact=True)).to_be_visible(timeout=15000)
    expect(panel.get_by_text("Registry.pol de equipo dañado", exact=True)).to_be_visible()
    shot(page, "22-directivas-revision")
    panel.get_by_role("button", name="Corregir y aplicar directivas").click()
    expect(page.get_by_text(re.compile(r"^Hecho: \d+ de \d+, verificados\.$"))).to_be_visible(
        timeout=20000
    )
    expect(page.get_by_text("Windows registró la aplicación")).to_be_visible()
    shot(page, "23-directivas-resultado")
    assert broken_domain.clock_offset_s < 300


def test_connectivity_solver_finds_the_layer_and_fixes_it(
    page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    network = SimulatedNetwork(wifi_disabled=True).install(monkeypatch)
    support_demo.SIMULATED.append(network)
    try:
        go(page, "#soporte?tool=network.connectivity&auto=1")
        panel = page.get_by_role(
            "region", name=re.compile(r"^La causa está en el adaptador de red")
        )
        expect(panel.get_by_text("Depende de la capa anterior").first).to_be_visible(timeout=15000)
        shot(page, "24-red-revision")
        panel.get_by_role("button", name="Corregir la conexión").click()
        expect(
            page.get_by_text("Hecho y verificado.").or_(page.get_by_text(re.compile("^Hecho:")))
        ).to_be_visible(timeout=20000)
        expect(page.get_by_text("Con internet", exact=True)).to_be_visible()
        shot(page, "25-red-resultado")
    finally:
        support_demo.SIMULATED.clear()


def test_printer_solver_picks_the_printer_and_fixes_it(
    page: Page, monkeypatch: pytest.MonkeyPatch
) -> None:
    printer = SimulatedPrinter(offline=True, stuck_jobs=2).install(monkeypatch)
    support_demo.SIMULATED.append(printer)
    try:
        go(page, "#soporte?tool=printers.fix")
        page.get_by_label("Oficina Láser (ficticia)").check()
        page.get_by_role("button", name="Revisar antes de hacerlo").click()
        panel = page.get_by_role("region", name=re.compile(r"^Se va a ponerla en línea"))
        expect(panel.get_by_text("Marcada «sin conexión»")).to_be_visible(timeout=15000)
        shot(page, "26-impresora-revision")
        panel.get_by_role("button", name="Corregir la impresora").click()
        expect(page.get_by_text("Lista para imprimir", exact=True)).to_be_visible(timeout=20000)
        shot(page, "27-impresora-resultado")
        assert printer.test_pages == 1 and printer.stuck_jobs == 0
    finally:
        support_demo.SIMULATED.clear()


def test_updates_solver_uses_the_error_code_to_fix(
    page: Page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    windows = SimulatedUpdates(
        tmp_path / "Windows", cache_broken=True, errors=[(0x80070002, "Acumulativa ficticia")]
    ).install(monkeypatch)
    support_demo.SIMULATED.append(windows)
    try:
        go(page, "#soporte?tool=system.updates&auto=1")
        panel = page.get_by_role("region", name=re.compile(r"^Se va a renovar la caché"))
        expect(panel.get_by_text("Error 0x80070002")).to_be_visible(timeout=15000)
        shot(page, "28-update-revision")
        panel.get_by_role("button", name="Corregir Windows Update").click()
        expect(
            page.get_by_text("La búsqueda funcionó: 4 actualizaciones pendientes")
        ).to_be_visible(timeout=20000)
        shot(page, "29-update-resultado")
    finally:
        support_demo.SIMULATED.clear()


def test_repair_solver_repairs_the_store_then_the_files(
    page: Page, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    windows = SimulatedRepair(tmp_path / "Windows", store=1, damaged_files=2).install(monkeypatch)
    support_demo.SIMULATED.append(windows)
    try:
        go(page, "#soporte?tool=system.repair&auto=1")
        page.get_by_role("button", name="Revisar y reparar Windows").click()
        expect(page.get_by_text("Reparó 2 archivos")).to_be_visible(timeout=20000)
        expect(page.get_by_text("Reinicie el equipo para terminar")).to_be_visible()
        shot(page, "30-reparacion-resultado")
    finally:
        support_demo.SIMULATED.clear()


def test_analysis_survives_leaving_and_can_be_refreshed(page: Page) -> None:
    go(page, "#soporte?tool=demo.analyze")
    page.get_by_role("button", name="Consultar").click()
    expect(page.locator('[data-table="archivos"] tbody tr')).to_have_count(15, timeout=10000)
    # Otra pantalla y de vuelta: el análisis sigue ahí, sin repetirlo.
    open_view(page, "Historial")
    go(page, "#soporte?tool=demo.analyze")
    expect(page.get_by_text(re.compile(r"^Resultado del "))).to_be_visible(timeout=10000)
    expect(page.locator('[data-table="archivos"] tbody tr')).to_have_count(15)
    page.get_by_role("button", name="Actualizar").click()
    expect(page.get_by_label("Versiones (2)")).to_be_visible(timeout=10000)
    expect(page.get_by_role("heading", name=re.compile(r"^Cambios desde el "))).to_be_visible()
    expect(page.get_by_text("Nada cambió de forma notable.")).to_be_visible()
    shot(page, "31-versiones")


def test_instant_action_runs_with_one_click_and_stays(page: Page) -> None:
    go(page, "#soporte?tool=demo.analyze&auto=1")
    table = page.locator('[data-table="archivos"]')
    expect(table.locator("tbody tr")).to_have_count(15, timeout=10000)
    table.locator('[data-action="demo.inspect"]').first.click()
    # Corre ahí mismo: un aviso dice cómo terminó y la pantalla no cambia.
    toast = page.get_by_role("list", name="Acciones en curso").get_by_role("listitem")
    expect(toast.get_by_text("Ver archivo")).to_be_visible(timeout=10000)
    expect(page).to_have_url(re.compile(r"tool=demo\.analyze"))
    expect(page.get_by_test_id("action-panel")).to_have_count(0)
    expect(toast).to_have_count(0, timeout=10000)  # lo que salió bien se va solo


def test_a_change_outside_the_screen_marks_the_result_stale(page: Page) -> None:
    from support_demo import DISK_STATE

    go(page, "#soporte?tool=demo.analyze&auto=1")
    expect(page.locator('[data-table="archivos"] tbody tr')).to_have_count(15, timeout=10000)
    stale = page.get_by_text(re.compile(r"^El equipo cambió después de este resultado"))
    expect(stale).to_have_count(0)
    DISK_STATE["version"] += 1  # algo cambió fuera de la pantalla (otra ventana, Windows)
    page.evaluate("window.dispatchEvent(new Event('focus'))")  # al volver a la ventana
    expect(stale).to_be_visible(timeout=10000)
    page.get_by_role("button", name="Actualizar").click()
    expect(stale).to_have_count(0, timeout=10000)

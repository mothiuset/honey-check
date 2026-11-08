"""Icono real en la bandeja de Windows: menú creado por el sistema y mensajes reales a la ventana.

No cubre el clic físico con el ratón: las opciones se eligen enviando a la ventana el mismo
mensaje WM_COMMAND que produce el menú.
"""

from __future__ import annotations

import ctypes
import threading
import time

import pytest

from honey_check.presentation.tray import TrayActions, TrayIcon

pytestmark = pytest.mark.windows_real

EXPECTED_MENU = [
    "Abrir Honey Check",
    "Analizar equipo",
    "Abrir la carpeta de inventarios",
    "Estado del servicio",
    "Salir de Honey Check",
]


class Recorder:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_on: str | None = None

    def action(self, name: str):
        def run() -> None:
            self.calls.append(name)
            if name == self.fail_on:
                raise OSError("fallo simulado de una acción")

        return run

    def status(self) -> str:
        self.calls.append("status")
        return "Servicio activo en el puerto 1234."


def wait_until(condition, timeout_s: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def tray():
    recorder = Recorder()
    icon = TrayIcon(
        TrayActions(
            open_ui=recorder.action("open"),
            start_scan=recorder.action("scan"),
            open_folder=recorder.action("folder"),
            status_text=recorder.status,
            exit_app=recorder.action("exit"),
        )
    )
    result: list[bool] = []
    thread = threading.Thread(target=lambda: result.append(icon.run()), daemon=True)
    thread.start()
    assert icon.wait_ready(10)
    if not icon.is_visible:
        pytest.skip("Esta sesión de Windows no tiene bandeja del sistema")
    yield icon, recorder, thread, result
    icon.stop()
    thread.join(10)


class TestRealTray:
    def test_menu_has_the_required_options(self, tray) -> None:
        labels, _ = tray[0].menu_snapshot()
        assert labels == EXPECTED_MENU

    def test_open_is_the_default_action(self, tray) -> None:
        _, default = tray[0].menu_snapshot()
        assert default == "Abrir Honey Check"

    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("Abrir Honey Check", "open"),
            ("Analizar equipo", "scan"),
            ("Abrir la carpeta de inventarios", "folder"),
            ("Estado del servicio", "status"),
            ("Salir de Honey Check", "exit"),
        ],
    )
    def test_each_option_runs_its_action(self, tray, label: str, expected: str) -> None:
        icon, recorder, *_ = tray
        icon.press(label)
        assert wait_until(lambda: expected in recorder.calls)

    def test_failed_action_does_not_close_the_tray(self, tray) -> None:
        icon, recorder, thread, _ = tray
        recorder.fail_on = "folder"
        icon.press("Abrir la carpeta de inventarios")
        assert wait_until(lambda: "folder" in recorder.calls)
        icon.press("Analizar equipo")
        assert wait_until(lambda: "scan" in recorder.calls)
        assert thread.is_alive()

    def test_notification_does_not_fail(self, tray) -> None:
        tray[0].notify("Notificación de prueba de Honey Check " + "x" * 400)

    def test_stop_ends_the_message_loop_and_removes_the_icon(self, tray) -> None:
        icon, _, thread, result = tray
        icon.stop()
        thread.join(10)
        assert not thread.is_alive()
        assert result == [True]
        assert icon.is_visible is False

    def test_notify_after_stop_is_harmless(self, tray) -> None:
        icon, _, thread, _ = tray
        icon.stop()
        thread.join(10)
        icon.notify("Tras cerrar")

    def test_explorer_restart_message_restores_the_icon(self, tray) -> None:
        icon, *_ = tray
        user32 = ctypes.WinDLL("user32")
        user32.PostMessageW.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        )
        assert icon._taskbar_created
        user32.PostMessageW(icon._hwnd, icon._taskbar_created, 0, 0)
        assert wait_until(lambda: icon.is_visible)


def noop_actions() -> TrayActions:
    noop = lambda: None  # noqa: E731
    return TrayActions(noop, noop, noop, lambda: "", noop)


def test_stop_requested_before_the_loop_starts_does_not_block() -> None:
    icon = TrayIcon(noop_actions())
    icon.stop()
    thread = threading.Thread(target=icon.run, daemon=True)
    thread.start()
    thread.join(15)
    assert not thread.is_alive()


def test_two_trays_can_run_in_sequence() -> None:
    for _ in range(2):
        icon = TrayIcon(noop_actions())
        thread = threading.Thread(target=icon.run, daemon=True)
        thread.start()
        assert icon.wait_ready(10)
        icon.stop()
        thread.join(10)
        assert not thread.is_alive()

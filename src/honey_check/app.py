"""Arranque y ciclo de vida de la aplicación portable."""

from __future__ import annotations

import argparse
import ctypes
import importlib
import json
import logging
import os
import secrets
import shutil
import sys
import threading
import time
from collections.abc import Sequence
from pathlib import Path

from honey_check import __version__
from honey_check.application.ports import DATA_DIR_NAME, SavedInventory
from honey_check.application.scan import ScanAlreadyRunning, ScanCoordinator, ScanState
from honey_check.application.service import InventoryService
from honey_check.composition import (
    close_interface,
    default_collectors,
    is_network_export_path,
    open_interface,
    probe_current_device,
    serve_support_worker,
    support_services,
    windows_ports,
)
from honey_check.infrastructure.device_store import (
    DeviceInventoryStore,
    InventoryNotFound,
    InventoryUnreadable,
    is_directory_writable,
)
from honey_check.infrastructure.runtime import (
    WorkspaceMonitor,
    configure_logging,
    executable_directory,
    is_frozen,
    leave_working_directory,
)
from honey_check.infrastructure.windows.elevation import (
    ElevatedProcess,
    ElevationCancelled,
    is_elevated,
    launch_elevated,
)
from honey_check.infrastructure.windows.instance import SingleInstance
from honey_check.infrastructure.windows.process import ProcessRunner
from honey_check.presentation.http.app import AppCallbacks, create_app
from honey_check.presentation.http.security import SessionGuard
from honey_check.presentation.http.server import LocalServer, ServerStartError
from honey_check.presentation.tray import TrayActions, TrayIcon

log = logging.getLogger("honey_check")

_MB_ICONERROR = 0x10
_EXIT_OK = 0
_EXIT_START_FAILED = 1
# La instancia elevada tarda en arrancar (UAC, descompresión del ejecutable, servidor).
_HANDOVER_TIMEOUT_S = 120.0
_HANDOVER_POLL_S = 0.25
_INSTANCE_WAIT_S = 20.0


def _app_commit() -> str | None:
    """Lo escribe el empaquetado; en desarrollo no existe."""
    try:
        return str(importlib.import_module("honey_check._build_info").COMMIT)
    except ImportError:
        return None


def build_label() -> str:
    """Lo que la app muestra como versión: «0.2.0 · compilación 412 · 2a16530 · 2026-11-07».

    El número de compilación siempre sube, así se ve de un vistazo si es la última. En desarrollo
    (sin empaquetar) lo dice.
    """
    try:
        info = importlib.import_module("honey_check._build_info")
    except ImportError:
        return f"{__version__} · desarrollo"
    label = (
        f"{__version__} · compilación {getattr(info, 'BUILD', '?')} · {str(info.COMMIT)[:7]}"
        f" · {str(getattr(info, 'BUILT_AT', ''))[:10]}"
    )
    return label + (" · con cambios sin commit" if getattr(info, "LOCAL_CHANGES", False) else "")


def pick_path(kind: str, title: str, patterns: str | None) -> str | None:
    """Diálogo de Windows para elegir una carpeta o un archivo, al frente del navegador."""
    from honey_check.infrastructure.windows.shell import pick_file, pick_folder  # noqa: PLC0415

    if kind == "folder":
        return pick_folder(title)
    return pick_file(title, patterns or "Todos los archivos (*.*)|*.*")


def _show_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, message, "Honey Check", _MB_ICONERROR)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="HoneyCheck", add_help=True)
    parser.add_argument("--output-dir", type=Path, help="carpeta de inventarios (desarrollo)")
    parser.add_argument("--no-browser", action="store_true", help="no abre el navegador")
    parser.add_argument("--no-tray", action="store_true", help="sin icono en la bandeja")
    parser.add_argument(
        "--status-file",
        type=Path,
        help="pruebas de empaquetado: escribe la URL de entrada en este archivo",
    )
    # Interno: proceso elevado de una sola acción de soporte (tubería y clave).
    parser.add_argument("--support-worker", nargs=2, help=argparse.SUPPRESS)
    # Interno: la instancia relanzada como administrador espera a que la anterior ceda su turno.
    parser.add_argument("--after-elevation", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    # La aplicación abandona el directorio de trabajo: las rutas deben ser absolutas desde ya.
    args.output_dir = args.output_dir.absolute() if args.output_dir else None
    args.status_file = args.status_file.absolute() if args.status_file else None
    return args


class Application:
    def __init__(self, args: argparse.Namespace, instance: SingleInstance) -> None:
        self._args = args
        self._instance = instance
        self._base_dir: Path = args.output_dir or executable_directory()
        self._stop = threading.Event()
        self._stopping = threading.Lock()
        self._elevated = is_elevated()
        self._handed_over = False
        self._guard = SessionGuard()
        self._runner = ProcessRunner()
        self._store = DeviceInventoryStore(self._base_dir / DATA_DIR_NAME)
        self._service = InventoryService(
            self._store,
            self._make_coordinator,
            is_directory_writable,
            on_saved=self._saved,
            on_export_failed=self._export_failed,
            is_network_path=is_network_export_path,
        )
        self._support, self._procedures = support_services(
            lambda: self._store.root,
            self._runner,
            self._support_environment,
            self._launch_support_worker,
        )
        self._support_inventory: tuple[str, object] | None = None
        self._server = LocalServer(self._make_app, self._guard.instance_id)
        self._monitor = WorkspaceMonitor(lambda: self._store.root, self._workspace_changed)
        self._tray = TrayIcon(
            TrayActions(
                open_ui=self.open_ui,
                start_scan=self.tray_scan,
                open_folder=lambda: self.open_folder(self._store.root),
                status_text=self.status_text,
                exit_app=self.request_exit,
            )
        )

    def _make_coordinator(self, on_finished: object) -> ScanCoordinator:
        return ScanCoordinator(
            default_collectors(),
            windows_ports(self._runner),
            __version__,
            _app_commit(),
            on_finished,  # type: ignore[arg-type]
        )

    def _make_app(self, port: object) -> object:
        return create_app(
            self._service,
            self._guard,
            port,  # type: ignore[arg-type]
            build_label(),
            AppCallbacks(
                self.open_folder,
                self.request_exit,
                self.elevate,
                lambda: self._elevated,
                pick_path,
            ),
            (InventoryNotFound, InventoryUnreadable),
            support=(self._support, self._procedures),
        )

    # --- Acciones --------------------------------------------------------------------------------

    def entry_url(self) -> str:
        return f"{self._server.base_url}/auth/{self._guard.issue_ticket()}"

    def open_ui(self) -> None:
        if not open_interface(self.entry_url(), self._store.root):
            log.warning("No se pudo abrir el navegador")
            self._tray.notify("No se pudo abrir el navegador.")

    def tray_scan(self) -> None:
        try:
            self._service.start_scan()
        except ScanAlreadyRunning:
            self._tray.notify("Ya hay un análisis en curso.")
            return
        self._tray.notify("Análisis iniciado. Le avisaremos cuando termine.")

    def open_folder(self, directory: Path) -> None:
        # Solo se abre la carpeta de inventarios, que no proviene de ninguna petición.
        os.startfile(directory)  # noqa: S606

    def status_text(self) -> str:
        workspace = self._service.workspace()
        progress = self._service.progress()
        health = "activo" if self._server.is_healthy() else "sin respuesta"
        lines = [f"Servicio {health} en el puerto {self._server.port}."]
        if progress.state is ScanState.RUNNING:
            lines.append(f"Analizando: {progress.completed}/{progress.total} módulos.")
        if not workspace.available:
            lines.append("La carpeta de inventarios no está disponible.")
        elif not workspace.writable:
            lines.append("La carpeta de inventarios no permite escribir.")
        return " ".join(lines)

    def request_exit(self) -> None:
        self._stop.set()
        self._tray.stop()

    # --- Ejecutar como administrador ---------------------------------------------------------

    def elevate(self) -> bool:
        """Relanza Honey Check con el aviso UAC; esta instancia cierra cuando la nueva responde.

        False si el técnico rechaza el aviso: entonces todo sigue igual.
        """
        # El relevo vive en la carpeta de datos, como el resto de datos de ejecución.
        handoff_dir = self._store.root / "relevo" / secrets.token_hex(6)
        handoff_dir.mkdir(parents=True, exist_ok=True)
        handoff = handoff_dir / "entrada.json"
        arguments = [
            *([] if is_frozen() else ["-m", "honey_check"]),
            "--output-dir",
            str(self._base_dir),
            "--no-browser",
            "--status-file",
            str(handoff),
            "--after-elevation",
            *(["--no-tray"] if self._args.no_tray else []),
        ]
        # La nueva instancia necesita el turno de instancia única; se recupera si algo falla.
        self._instance.release()
        try:
            process = launch_elevated(sys.executable, arguments, str(self._base_dir))
        except BaseException as error:
            self._reclaim_instance()
            shutil.rmtree(handoff_dir, ignore_errors=True)
            if isinstance(error, ElevationCancelled):
                log.info("Se canceló el aviso de administrador")
                return False
            raise
        log.info("Honey Check se relanzó como administrador")
        threading.Thread(
            target=self._hand_over, args=(process, handoff), name="elevation", daemon=True
        ).start()
        return True

    def _hand_over(self, process: ElevatedProcess, handoff: Path) -> None:
        """Abre el navegador sin elevar con la entrada de la instancia nueva y cierra esta."""
        deadline = time.monotonic() + _HANDOVER_TIMEOUT_S
        try:
            while time.monotonic() < deadline:
                if handoff.is_file():
                    url = json.loads(handoff.read_text(encoding="utf-8"))["url"]
                    if not open_interface(url, self._store.root):
                        log.warning("No se pudo abrir el navegador")
                    # La ventana ya es de la instancia elevada: esta no debe cerrarla al salir.
                    self._handed_over = True
                    self.request_exit()
                    return
                if process.has_exited():
                    break
                time.sleep(_HANDOVER_POLL_S)
        except (OSError, ValueError, KeyError):
            log.exception("No se pudo leer la entrada de la instancia elevada")
        finally:
            process.close()
            shutil.rmtree(handoff.parent, ignore_errors=True)
        log.warning("La instancia elevada no respondió; sigue la actual")
        self._reclaim_instance()
        self._tray.notify("No se pudo iniciar Honey Check como administrador.")

    def _launch_support_worker(self, arguments: list[str]) -> ElevatedProcess:
        """Una acción de soporte como administrador: aviso UAC y proceso aparte."""
        prefix = [] if is_frozen() else ["-m", "honey_check"]
        return launch_elevated(sys.executable, [*prefix, *arguments], str(self._base_dir))

    def _reclaim_instance(self) -> None:
        if self._instance.acquire():
            self._instance.watch_activation(self.open_ui)

    def _support_environment(self) -> tuple[bool | None, object]:
        """Permisos y último inventario de este equipo para las herramientas de soporte."""
        current = self._service.current_device
        history = self._service.history(current.device_key) if current else []
        newest = next((item for item in history if not item.invalid_reason), None)
        if newest is None:
            return self._elevated, None
        cached = self._support_inventory
        if cached is None or cached[0] != newest.inventory_id:
            try:
                self._support_inventory = (
                    newest.inventory_id,
                    self._service.load(newest.inventory_id),
                )
            except (InventoryNotFound, InventoryUnreadable):
                return self._elevated, None
        return self._elevated, self._support_inventory[1] if self._support_inventory else None

    # --- Avisos ----------------------------------------------------------------------------------

    def _saved(self, saved: SavedInventory) -> None:
        self._tray.notify(f"Inventario guardado: {saved.path.name}")

    def _export_failed(self, reason: str) -> None:
        self._tray.notify("No se pudo guardar el inventario. Abra Honey Check para elegir destino.")

    def _workspace_changed(self, available: bool) -> None:
        self._tray.notify(
            "La carpeta de Honey Check vuelve a estar disponible."
            if available
            else "La carpeta de Honey Check dejó de estar disponible. ¿Se retiró la USB?"
        )

    # --- Ciclo de vida ---------------------------------------------------------------------------

    def run(self) -> int:
        leave_working_directory()
        try:
            self._server.start()
        except ServerStartError as error:
            log.error("No se pudo iniciar el servidor local: %s", error)
            _show_error(
                "Honey Check no pudo iniciar su servicio local.\n"
                "Revise la carpeta logs o las directivas de este equipo."
            )
            self._runner.close()
            return _EXIT_START_FAILED

        self._instance.watch_activation(self.open_ui)
        self._store.ensure_root()
        threading.Thread(target=self._prepare_data, name="prepare-data", daemon=True).start()
        self._monitor.start()
        self._write_status_file()
        if not self._args.no_browser:
            # El servidor ya respondió a la comprobación de salud: ahora sí se abre el navegador.
            self.open_ui()

        try:
            shown = False if self._args.no_tray else self._run_tray()
            if not shown:
                # Sin bandeja se sigue funcionando; la interfaz ofrece la opción de salir.
                self._stop.wait()
        finally:
            self.shutdown()
        return _EXIT_OK

    def _prepare_data(self) -> None:
        """En segundo plano: la interfaz abre sin esperar a la sonda ni a la migración."""
        try:
            report = self._store.import_legacy(self._base_dir)
            for problem in report.skipped:
                log.warning("Inventario suelto sin mover: %s", problem)
        except Exception:  # noqa: BLE001 - la migración nunca debe impedir el uso
            log.exception("No se pudieron mover los inventarios sueltos")
        device = probe_current_device(self._runner)
        if device is not None and self._service.current_device is None:
            self._service.set_current_device(device)

    def _run_tray(self) -> bool:
        try:
            return self._tray.run()
        except OSError as error:
            log.warning("Bandeja no disponible: %s", type(error).__name__)
            return False

    def _write_status_file(self) -> None:
        path: Path | None = self._args.status_file
        if path is None:
            return
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"url": self.entry_url(), "pid": os.getpid(), "port": self._server.port}),
            encoding="utf-8",
        )
        temporary.replace(path)

    def shutdown(self) -> None:
        if not self._stopping.acquire(blocking=False):
            return
        log.info("Cerrando Honey Check")
        self._stop.set()
        self._monitor.stop()
        self._service.shutdown()
        self._support.shutdown()
        self._runner.close()
        self._server.stop()
        if not self._handed_over:
            close_interface(self._store.root)
        self._instance.release()
        log.info("Honey Check cerrado")


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.support_worker:
        # Sin instancia única, servidor ni bandeja: ejecuta una acción y termina.
        leave_working_directory()
        address, key = args.support_worker
        return serve_support_worker(address, key, ProcessRunner())
    configure_logging((args.output_dir or executable_directory()) / DATA_DIR_NAME)
    log.info("Honey Check %s iniciado", build_label())

    instance = SingleInstance()
    acquired = instance.acquire()
    deadline = time.monotonic() + _INSTANCE_WAIT_S
    while not acquired and args.after_elevation and time.monotonic() < deadline:
        time.sleep(_HANDOVER_POLL_S)
        acquired = instance.acquire()
    if not acquired:
        log.info("Ya hay una instancia en ejecución: se le pide abrir su interfaz")
        instance.signal_existing()
        return _EXIT_OK
    try:
        return Application(args, instance).run()
    except Exception:
        log.exception("Fallo inesperado al iniciar")
        _show_error("Honey Check encontró un error inesperado. Revise la carpeta logs.")
        instance.release()
        return _EXIT_START_FAILED


__all__ = ["Application", "main"]

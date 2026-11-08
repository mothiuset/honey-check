"""Instancia única, logs y vigilancia de carpeta contra objetos reales de Windows."""

from __future__ import annotations

import logging
import shutil
import threading
import uuid
from pathlib import Path

import pytest

from honey_check.infrastructure.runtime import WorkspaceMonitor, configure_logging
from honey_check.infrastructure.windows.instance import SingleInstance

pytestmark = pytest.mark.windows_real


def unique_name() -> str:
    return f"HoneyCheckPrueba-{uuid.uuid4().hex}"


class TestSingleInstance:
    def test_second_instance_is_refused(self) -> None:
        name = unique_name()
        first, second = SingleInstance(name), SingleInstance(name)
        try:
            assert first.acquire() is True
            assert second.acquire() is False
        finally:
            first.release()

    def test_released_instance_can_be_reacquired(self) -> None:
        name = unique_name()
        first, second = SingleInstance(name), SingleInstance(name)
        assert first.acquire() is True
        first.release()
        assert second.acquire() is True
        second.release()

    def test_second_instance_activates_the_first(self) -> None:
        name = unique_name()
        first, second = SingleInstance(name), SingleInstance(name)
        activated = threading.Event()
        try:
            assert first.acquire()
            first.watch_activation(activated.set)
            assert second.signal_existing()
            assert activated.wait(5)
        finally:
            first.release()

    def test_release_is_idempotent(self) -> None:
        instance = SingleInstance(unique_name())
        instance.acquire()
        instance.release()
        instance.release()


class TestWorkspaceMonitor:
    def test_detects_removal_and_return(self, tmp_path: Path) -> None:
        usb = tmp_path / "usb"
        usb.mkdir()
        changes: list[bool] = []
        monitor = WorkspaceMonitor(lambda: usb, changes.append)
        monitor.check_once()
        assert changes == []
        shutil.rmtree(usb)
        monitor.check_once()
        assert changes == [False]
        assert monitor.available is False
        monitor.check_once()
        assert changes == [False]
        usb.mkdir()
        monitor.check_once()
        assert changes == [False, True]

    def test_background_loop_stops_cleanly(self, tmp_path: Path) -> None:
        changed = threading.Event()
        target = tmp_path / "no-existe"
        monitor = WorkspaceMonitor(lambda: target, lambda _: changed.set(), interval_s=0.05)
        monitor.start()
        assert changed.wait(5)
        monitor.stop()


class TestLogging:
    @pytest.fixture(autouse=True)
    def isolated_root(self):
        root = logging.getLogger()
        saved = list(root.handlers)
        root.handlers = []
        yield
        for handler in root.handlers:
            handler.close()
        root.handlers = saved

    def test_logs_next_to_executable_and_redacted(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setenv("USERPROFILE", r"C:\Users\persona-ficticia")
        monkeypatch.setenv("COMPUTERNAME", "EQUIPO-FICTICIO")
        setup = configure_logging(tmp_path)
        assert setup.directory == tmp_path / "logs"
        assert setup.fallback_used is False
        logging.getLogger("prueba").warning(r"ruta C:\Users\persona-ficticia\a en EQUIPO-FICTICIO")
        for handler in logging.getLogger().handlers:
            handler.flush()
        content = (tmp_path / "logs" / "honey-check.log").read_text(encoding="utf-8")
        assert "persona-ficticia" not in content
        assert "EQUIPO-FICTICIO" not in content
        assert "<redactado>" in content

    def test_unwritable_folder_falls_back(self, tmp_path: Path) -> None:
        blocked = tmp_path / "archivo"
        blocked.write_text("no es una carpeta", encoding="utf-8")
        setup = configure_logging(blocked)
        assert setup.fallback_used is True

    def test_log_failure_never_propagates(self, tmp_path: Path) -> None:
        setup = configure_logging(tmp_path)
        assert setup.directory is not None
        for handler in logging.getLogger().handlers:
            handler.close()
        shutil.rmtree(setup.directory, ignore_errors=True)
        logging.getLogger("prueba").error("no debe lanzar excepción")

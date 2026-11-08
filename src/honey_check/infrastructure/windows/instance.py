"""Instancia única por sesión de usuario, sin archivos: un mutex y un evento de Windows.

La segunda ejecución no recibe datos de la primera: solo le pide que abra su propia interfaz.
"""

from __future__ import annotations

import ctypes
import threading
from collections.abc import Callable
from ctypes import wintypes

_ERROR_ALREADY_EXISTS = 183
_WAIT_OBJECT_0 = 0
_POLL_MS = 300

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
_kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


class SingleInstance:
    def __init__(self, name: str = "HoneyCheck") -> None:
        # `Local\` limita el nombre a la sesión actual: otro usuario tiene su propia instancia.
        self._mutex_name = f"Local\\{name}-Instance"
        self._event_name = f"Local\\{name}-Activate"
        self._mutex: int | None = None
        self._event: int | None = None
        self._stop = threading.Event()
        self._watcher: threading.Thread | None = None

    def acquire(self) -> bool:
        """True si esta es la primera instancia. El sistema libera el mutex si el proceso muere."""
        ctypes.set_last_error(0)
        handle = _kernel32.CreateMutexW(None, False, self._mutex_name)
        error = ctypes.get_last_error()
        if not handle:
            raise ctypes.WinError(error)
        if error == _ERROR_ALREADY_EXISTS:
            _kernel32.CloseHandle(handle)
            return False
        self._mutex = handle
        self._event = _kernel32.CreateEventW(None, False, False, self._event_name)
        self._stop.clear()  # Puede volver a tomarse tras cederla (relanzar elevado y cancelar).
        return True

    def signal_existing(self) -> bool:
        """Pide a la instancia en ejecución que abra su interfaz."""
        handle = _kernel32.CreateEventW(None, False, False, self._event_name)
        if not handle:
            return False
        try:
            return bool(_kernel32.SetEvent(handle))
        finally:
            _kernel32.CloseHandle(handle)

    def watch_activation(self, on_activate: Callable[[], None]) -> None:
        event = self._event
        if event is None:
            return

        def loop() -> None:
            while not self._stop.is_set():
                if _kernel32.WaitForSingleObject(event, _POLL_MS) == _WAIT_OBJECT_0:
                    on_activate()

        self._watcher = threading.Thread(target=loop, name="instance-activation", daemon=True)
        self._watcher.start()

    def release(self) -> None:
        self._stop.set()
        if self._watcher is not None:
            self._watcher.join(2)
        for handle in (self._event, self._mutex):
            if handle:
                _kernel32.CloseHandle(handle)
        self._event = None
        self._mutex = None

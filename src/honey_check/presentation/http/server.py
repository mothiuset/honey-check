"""Servidor local: el sistema operativo elige el puerto y el socket ya está ocupado al usarlo."""

from __future__ import annotations

import http.client
import json
import logging
import socket
import threading
import time
from collections.abc import Callable

import uvicorn
from uvicorn.protocols.http.h11_impl import H11Protocol

log = logging.getLogger(__name__)

LOOPBACK = "127.0.0.1"
_HEALTH_TIMEOUT_S = 15.0
_START_ATTEMPTS = 3
_STOP_TIMEOUT_S = 8.0


class ServerStartError(Exception):
    pass


def bind_loopback_socket() -> socket.socket:
    """Puerto 0: lo asigna Windows al crear el socket, de modo que no hay carrera ni conflicto.

    SO_EXCLUSIVEADDRUSE impide que otro proceso se enganche al mismo puerto.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        sock.bind((LOOPBACK, 0))
        sock.listen(64)
        sock.set_inheritable(False)
    except OSError:
        sock.close()
        raise
    return sock


def probe_health(port: int, instance_id: str, timeout_s: float = 2.0) -> bool:
    """Comprueba que quien responde es esta ejecución y no otro proceso en ese puerto."""
    connection = http.client.HTTPConnection(LOOPBACK, port, timeout=timeout_s)
    try:
        connection.request("GET", "/health", headers={"Host": f"{LOOPBACK}:{port}"})
        response = connection.getresponse()
        if response.status != 200:
            return False
        return bool(json.loads(response.read()).get("instance") == instance_id)
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


class LocalServer:
    """Hilo de uvicorn con arranque verificado, reintento controlado y parada limpia."""

    def __init__(
        self,
        app_factory: Callable[[Callable[[], int]], object],
        instance_id: str,
        bind: Callable[[], socket.socket] = bind_loopback_socket,
    ) -> None:
        self._app_factory = app_factory
        self._instance_id = instance_id
        self._bind = bind
        self._port = 0
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None

    @property
    def port(self) -> int:
        return self._port

    @property
    def base_url(self) -> str:
        return f"http://{LOOPBACK}:{self._port}"

    def start(self) -> None:
        last_error = "desconocido"
        for attempt in range(1, _START_ATTEMPTS + 1):
            try:
                self._start_once()
            except OSError as error:
                last_error = type(error).__name__
                log.warning("Intento %d de arranque fallido: %s", attempt, last_error)
            else:
                if self._wait_until_healthy():
                    log.info("Servidor local disponible (intento %d)", attempt)
                    return
                last_error = "el servidor no respondió a la comprobación de salud"
                log.warning("Intento %d de arranque sin respuesta", attempt)
                self.stop()
        raise ServerStartError(last_error)

    def _start_once(self) -> None:
        self._socket = self._bind()
        self._port = self._socket.getsockname()[1]
        config = uvicorn.Config(
            self._app_factory(lambda: self._port),  # type: ignore[arg-type]
            log_config=None,
            access_log=False,
            server_header=False,
            date_header=False,
            lifespan="off",
            ws="none",
            http=H11Protocol,
            loop="asyncio",
            timeout_graceful_shutdown=3,
            timeout_keep_alive=5,
            limit_concurrency=32,
        )
        server = uvicorn.Server(config)
        self._server = server
        sock = self._socket
        self._thread = threading.Thread(
            target=server.run, kwargs={"sockets": [sock]}, name="http-server", daemon=True
        )
        self._thread.start()

    def _wait_until_healthy(self) -> bool:
        deadline = time.monotonic() + _HEALTH_TIMEOUT_S
        while time.monotonic() < deadline:
            thread = self._thread
            if thread is None or not thread.is_alive():
                return False
            if probe_health(self._port, self._instance_id):
                return True
            time.sleep(0.05)
        return False

    def is_healthy(self) -> bool:
        return self._port != 0 and probe_health(self._port, self._instance_id)

    def stop(self) -> None:
        server, thread, sock = self._server, self._thread, self._socket
        if server is not None:
            server.should_exit = True
        if thread is not None and thread.is_alive():
            thread.join(_STOP_TIMEOUT_S)
            if thread.is_alive():
                log.warning("El servidor no se detuvo a tiempo; se fuerza la salida")
                if server is not None:
                    server.force_exit = True
                thread.join(2)
        if sock is not None:
            sock.close()
        self._server = None
        self._thread = None
        self._socket = None

"""Una acción de soporte como administrador, en un proceso aparte, sin reiniciar Honey Check.

La instancia del técnico (sin elevar) abre una tubería con nombre aleatorio y lanza
`HoneyCheck.exe --support-worker <tubería> <clave>` con el aviso UAC. Ambos lados se autentican
con la clave (desafío HMAC de `multiprocessing.connection`) y se hablan con JSON, nunca pickle.
El proceso elevado vuelve a validar los parámetros contra la definición, ejecuta solo esa
herramienta, reenvía registro y avance en vivo, atiende la cancelación y termina. Los secretos
viajan por la tubería: nunca tocan el disco ni la línea de comandos.
"""

from __future__ import annotations

import contextlib
import json
import logging
import secrets
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict
from multiprocessing.connection import Client, Connection, Listener, PipeConnection
from pathlib import Path
from typing import Any

from honey_check.application.ports import CancelToken, CollectionCancelled
from honey_check.application.support.context import RunContext
from honey_check.application.support.params import validate
from honey_check.application.support.ports import (
    CommandFailed,
    ElevationDeclined,
    RunRecorder,
    SupportEnvironment,
    Tool,
    UserSession,
)
from honey_check.domain.inventory import Inventory
from honey_check.domain.support import LogLevel, ToolResult
from honey_check.infrastructure.windows.elevation import ElevatedProcess, ElevationCancelled

log = logging.getLogger(__name__)

_CONNECT_TIMEOUT_S = 600.0  # el aviso UAC puede quedar abierto mientras el técnico decide
_POLL_S = 0.2
_FAMILY = "AF_PIPE"

Launch = Callable[[list[str]], ElevatedProcess]
# En Windows, Listener/Client con AF_PIPE devuelven PipeConnection.
Channel = Connection | PipeConnection


class ElevatedToolRunner:
    """Implementa ElevatedExecutor: lanza el proceso elevado y reenvía lo que hace."""

    def __init__(self, launch: Launch) -> None:
        self._launch = launch

    def execute(
        self,
        tool_id: str,
        params: Mapping[str, Any],
        env: SupportEnvironment,
        recorder: RunRecorder,
    ) -> ToolResult:
        address = rf"\\.\pipe\honeycheck-{secrets.token_hex(12)}"
        key = secrets.token_bytes(32)
        listener = Listener(address, family=_FAMILY, authkey=key)
        try:
            try:
                process = self._launch(["--support-worker", address, key.hex()])
            except ElevationCancelled as error:
                raise ElevationDeclined(tool_id) from error
            try:
                connection = self._accept(listener, address, key, process, recorder.cancel)
                with connection:
                    request = {
                        "tool": tool_id,
                        "params": dict(params),
                        "dataRoot": str(env.data_root),
                        "inventory": env.inventory.model_dump(mode="json", by_alias=True)
                        if env.inventory
                        else None,
                        "user": asdict(env.user) if env.user else None,
                    }
                    connection.send_bytes(json.dumps(request).encode("utf-8"))
                    return self._relay(connection, process, recorder)
            finally:
                process.close()
        finally:
            listener.close()

    @staticmethod
    def _accept(
        listener: Listener,
        address: str,
        key: bytes,
        process: ElevatedProcess,
        cancel: CancelToken,
    ) -> Channel:
        accepted: list[Channel] = []
        failure: list[BaseException] = []

        def accept() -> None:
            try:
                accepted.append(listener.accept())
            except BaseException as error:  # noqa: BLE001 - se informa en el hilo principal
                failure.append(error)

        thread = threading.Thread(target=accept, name="soporte-elevado", daemon=True)
        thread.start()
        deadline = time.monotonic() + _CONNECT_TIMEOUT_S
        while thread.is_alive():
            thread.join(_POLL_S)
            if not thread.is_alive():
                break
            if process.has_exited() or cancel.cancelled or time.monotonic() > deadline:
                # Desbloquea accept() conectándose uno mismo; esa conexión se descarta.
                with contextlib.suppress(OSError):
                    Client(address, family=_FAMILY, authkey=key).close()
                thread.join(5)
                for connection in accepted:
                    connection.close()
                cancel.raise_if_cancelled()
                raise CommandFailed("El proceso de administrador no respondió")
        if failure or not accepted:
            raise CommandFailed("No se pudo hablar con el proceso de administrador")
        return accepted[0]

    @staticmethod
    def _relay(connection: Channel, process: ElevatedProcess, recorder: RunRecorder) -> ToolResult:
        cancel_sent = False
        while True:
            if recorder.cancel.cancelled and not cancel_sent:
                connection.send_bytes(b'{"type": "cancel"}')
                cancel_sent = True
            try:
                ready = connection.poll(_POLL_S)
            except (EOFError, OSError) as error:
                raise CommandFailed("El proceso de administrador se cerró") from error
            if not ready:
                if process.has_exited() and not connection.poll(0):
                    raise CommandFailed("El proceso de administrador terminó sin resultado")
                continue
            try:
                message = json.loads(connection.recv_bytes())
            except (EOFError, OSError) as error:
                raise CommandFailed("El proceso de administrador se cerró") from error
            kind = message.get("type")
            if kind == "log":
                recorder.record(LogLevel(message["level"]), str(message["text"]))
            elif kind == "progress":
                recorder.progress(int(message["done"]), int(message["total"]), message.get("label"))
            elif kind == "result":
                return ToolResult.model_validate(message["result"])
            elif kind == "cancelled":
                raise CollectionCancelled
            elif kind == "precondition":
                raise ValueError(str(message["message"]))
            elif kind == "error":
                raise CommandFailed(str(message["message"]))


# --- Lado elevado -------------------------------------------------------------------------------


class _Sender:
    def __init__(self, connection: Channel) -> None:
        self._connection = connection
        self._lock = threading.Lock()

    def send(self, message: dict[str, Any]) -> None:
        data = json.dumps(message, default=str).encode("utf-8")
        with self._lock:
            self._connection.send_bytes(data)


def serve(
    address: str,
    key_hex: str,
    tools: Mapping[str, Tool],
    environment: Callable[[Path, Inventory | None, UserSession | None], SupportEnvironment],
) -> int:
    """Ejecuta la única herramienta que pide la instancia del técnico y devuelve el código."""
    connection = Client(address, family=_FAMILY, authkey=bytes.fromhex(key_hex))
    sender = _Sender(connection)
    with connection:
        request = json.loads(connection.recv_bytes())
        tool = tools.get(str(request.get("tool")))
        data_root = Path(str(request.get("dataRoot")))
        if tool is None or not data_root.is_dir():
            sender.send({"type": "error", "message": "Petición no válida"})
            return 2
        raw_inventory = request.get("inventory")
        inventory = Inventory.model_validate(raw_inventory) if raw_inventory else None
        raw_user = request.get("user")
        user = UserSession(**{k: str(v) for k, v in raw_user.items()}) if raw_user else None
        env = environment(data_root, inventory, user)
        cancel = CancelToken()
        try:
            values = validate(tool.definition, request.get("params") or {})
        except ValueError as error:
            sender.send({"type": "precondition", "message": str(error)})
            return 2

        sent = {"log": 0}
        secret_values = [
            str(values[p.name])
            for p in tool.definition.params
            if p.kind.value == "secret" and values.get(p.name)
        ]

        def forward() -> None:
            entries = context.log[sent["log"] :]
            sent["log"] += len(entries)
            for entry in entries:
                sender.send({"type": "log", "level": entry.level.value, "text": entry.text})
            state = context.progress_state
            sender.send(
                {"type": "progress", "done": state.done, "total": state.total, "label": state.label}
            )

        context = RunContext(env, cancel, secrets.token_hex(8), forward, secret_values)

        def listen() -> None:
            try:
                while True:
                    if json.loads(connection.recv_bytes()).get("type") == "cancel":
                        cancel.cancel()
            except (EOFError, OSError, ValueError):
                cancel.cancel()  # la instancia del técnico se fue: no seguir sola

        threading.Thread(target=listen, name="soporte-cancelar", daemon=True).start()
        try:
            result = tool.execute(values, context)
        except CollectionCancelled:
            sender.send({"type": "cancelled"})
            return 1
        except (ValueError, PermissionError, LookupError) as error:
            sender.send({"type": "precondition", "message": str(error) or type(error).__name__})
            return 1
        except Exception as error:  # noqa: BLE001 - toda falla vuelve al registro de la acción
            log.exception("Herramienta %s falló como administrador", tool.definition.id)
            sender.send({"type": "error", "message": str(error) or type(error).__name__})
            return 1
        sender.send({"type": "result", "result": result.model_dump(mode="json", by_alias=True)})
        return 0

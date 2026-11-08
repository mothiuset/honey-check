"""Registro de las acciones de soporte en HoneyCheck-datos\\acciones.

Cada ejecución es una versión: su resultado completo va comprimido (`.json.gz`, un análisis de
disco entero pasa de megas a cientos de kilobytes) y una línea liviana en `indice.jsonl` permite
listar versiones sin abrir ningún resultado. Los registros anteriores (`.json` sin comprimir)
se siguen leyendo.
"""

from __future__ import annotations

import contextlib
import gzip
import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from honey_check.domain.support import Run
from honey_check.infrastructure.device_store import write_new_file

log = logging.getLogger(__name__)

_FOLDER = "acciones"
_INDEX = "indice.jsonl"
_MAX_BYTES = 64 * 1024 * 1024  # sin comprimir; por encima se guarda el registro sin los datos


class FileRunJournal:
    def __init__(self, data_root: Callable[[], Path]) -> None:
        self._data_root = data_root
        self._lock = threading.Lock()

    def _folder(self) -> Path:
        return self._data_root() / _FOLDER

    def save(self, run: Run) -> None:
        folder = self._folder()
        folder.mkdir(parents=True, exist_ok=True)
        payload = run.model_dump_json(by_alias=True).encode("utf-8")
        if len(payload) > _MAX_BYTES:
            payload = (
                run.model_copy(update={"result": None}).model_dump_json(by_alias=True).encode()
            )
        name = f"{run.started_at:%Y%m%dT%H%M%SZ}_{run.tool}_{run.id}.json.gz"
        with contextlib.suppress(FileExistsError):
            write_new_file(folder / name, gzip.compress(payload, compresslevel=6))
        light = run.model_copy(
            update={"result": _summary_only(run), "log": run.log[-5:]}
        ).model_dump_json(by_alias=True)
        with self._lock, (folder / _INDEX).open("a", encoding="utf-8") as index:
            index.write(light + "\n")

    def recent(self, limit: int, tool: str | None = None) -> list[Run]:
        """Versiones más recientes primero, livianas (solo el resumen del resultado)."""
        runs = self._from_index(tool)
        if not runs:
            runs = self._from_files(tool)
        runs.sort(key=lambda r: r.started_at, reverse=True)
        return runs[:limit]

    def load(self, run_id: str) -> Run | None:
        """La versión completa, con su resultado."""
        if not run_id.isalnum():
            return None
        try:
            candidates = list(self._folder().glob(f"*_{run_id}.json*"))
        except OSError:
            return None
        for path in candidates:
            run = _read(path)
            if run is not None:
                return run
        return None

    def _from_index(self, tool: str | None) -> list[Run]:
        try:
            lines = (self._folder() / _INDEX).read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        runs: dict[str, Run] = {}
        for line in lines:
            try:
                run = Run.model_validate_json(line)
            except ValidationError:
                continue
            if tool is None or run.tool == tool:
                runs[run.id] = run
        # Registros de antes del índice: se agregan una vez desde sus archivos.
        known = set(runs)
        for run in self._from_files(tool, skip=known, compressed=False):
            runs.setdefault(run.id, run)
        return list(runs.values())

    def _from_files(
        self, tool: str | None, skip: set[str] | None = None, compressed: bool = True
    ) -> list[Run]:
        try:
            files = sorted(self._folder().glob("*.json*"), reverse=True)
        except OSError:
            return []
        runs = []
        for path in files[:300]:
            if path.suffix == ".gz" and not compressed:
                continue
            parts = path.name.split(".")[0].split("_", 2)
            if len(parts) == 3 and ((tool and parts[1] != tool) or (skip and parts[2] in skip)):
                continue
            run = _read(path)
            if run is not None:
                runs.append(run.model_copy(update={"result": _summary_only(run)}))
        return runs


def _summary_only(run: Run) -> object:
    if run.result is None:
        return None
    return run.result.model_copy(update={"tables": [], "charts": [], "text": None})


def _read(path: Path) -> Run | None:
    try:
        raw = path.read_bytes()
        if path.suffix == ".gz":
            raw = gzip.decompress(raw)
        if len(raw) > _MAX_BYTES:
            return None
        return Run.model_validate(json.loads(raw.decode("utf-8")))
    except (OSError, ValueError, ValidationError, EOFError):
        log.info("Registro de acción ilegible: %s", path.name)
        return None

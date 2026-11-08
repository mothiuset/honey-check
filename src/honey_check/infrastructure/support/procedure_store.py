"""Procesos en HoneyCheck-datos\\procesos: <slug>\\v0001.json… y ejecuciones\\<id>.json."""

from __future__ import annotations

import json
import logging
import re
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from honey_check.domain.procedures import SLUG, Procedure, ProcedureRun
from honey_check.infrastructure.device_store import write_new_file

log = logging.getLogger(__name__)

_VERSION = re.compile(r"^v(\d{4,})\.json$")
_RUN_ID = re.compile(r"^[0-9a-f]{16}$")


class FileProcedureStore:
    def __init__(self, data_root: Callable[[], Path]) -> None:
        self._data_root = data_root

    def _root(self) -> Path:
        return self._data_root() / "procesos"

    def _runs(self) -> Path:
        return self._root() / "ejecuciones"

    def versions(self, slug: str) -> list[Procedure]:
        if not SLUG.match(slug):
            return []
        folder = self._root() / slug
        found = []
        for path in folder.glob("v*.json") if folder.is_dir() else []:
            if not _VERSION.match(path.name):
                continue
            try:
                found.append(Procedure.model_validate(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError, ValidationError):
                log.info("Proceso ilegible: %s", path)
        return sorted(found, key=lambda p: p.version, reverse=True)

    def saved(self) -> list[Procedure]:
        root = self._root()
        if not root.is_dir():
            return []
        latest = []
        for folder in root.iterdir():
            if folder.is_dir() and SLUG.match(folder.name):
                versions = self.versions(folder.name)
                if versions:
                    latest.append(versions[0])
        return latest

    def save(self, procedure: Procedure) -> Procedure:
        folder = self._root() / procedure.slug
        folder.mkdir(parents=True, exist_ok=True)
        current = self.versions(procedure.slug)
        version = (current[0].version if current else 0) + 1
        for _ in range(100):
            saved = procedure.model_copy(update={"version": version})
            try:
                write_new_file(
                    folder / f"v{version:04d}.json",
                    saved.model_dump_json(by_alias=True, indent=2).encode("utf-8"),
                )
                return saved
            except FileExistsError:
                version += 1
        raise OSError("no se pudo asignar una versión al proceso")

    def remove(self, slug: str) -> int:
        """Mueve todas las versiones a la papelera de la carpeta de datos."""
        folder = self._root() / slug
        if not SLUG.match(slug) or not folder.is_dir():
            return 0
        count = len(self.versions(slug))
        target = (
            self._data_root()
            / "papelera"
            / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}_{secrets.token_hex(3)}"
            / "procesos"
            / slug
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        folder.rename(target)
        return count

    def save_run(self, run: ProcedureRun) -> None:
        folder = self._runs()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{run.id}.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(run.model_dump_json(by_alias=True, indent=2), encoding="utf-8")
        temporary.replace(path)

    def run(self, run_id: str) -> ProcedureRun | None:
        if not _RUN_ID.match(run_id):
            return None
        try:
            return ProcedureRun.model_validate(
                json.loads((self._runs() / f"{run_id}.json").read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, ValidationError):
            return None

    def runs(self, limit: int) -> list[ProcedureRun]:
        folder = self._runs()
        if not folder.is_dir():
            return []
        result = []
        for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[
            :limit
        ]:
            try:
                result.append(
                    ProcedureRun.model_validate(json.loads(path.read_text(encoding="utf-8")))
                )
            except (OSError, ValueError, ValidationError):
                continue
        return result

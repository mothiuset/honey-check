"""Recorrido de carpetas para medir espacio, sin seguir uniones ni enlaces simbólicos."""

from __future__ import annotations

import fnmatch
import os
import stat
import time
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from honey_check.application.support.ports import ToolContext

_REPARSE = 0x400
_PROGRESS_EVERY = 4000


@dataclass
class Node:
    name: str
    path: str
    size: int = 0
    files: int = 0
    children: list[Node] = field(default_factory=list)


@dataclass
class Scan:
    root: Node
    largest_files: list[tuple[int, str, float]]
    by_extension: Counter[str]
    denied: int = 0
    files: int = 0
    folders: int = 0
    elapsed_s: float = 0.0


def _is_reparse(entry: os.DirEntry[str]) -> bool:
    try:
        info = entry.stat(follow_symlinks=False)
    except OSError:
        return True
    return bool(getattr(info, "st_file_attributes", 0) & _REPARSE) or entry.is_symlink()


def scan_tree(path: Path, ctx: ToolContext, *, keep_files: int = 60, depth_limit: int = 64) -> Scan:
    """Tamaño de cada carpeta; los archivos más grandes y el total por extensión."""
    started = time.monotonic()
    largest: list[tuple[int, str, float]] = []
    by_extension: Counter[str] = Counter()
    counters = {"files": 0, "folders": 0, "denied": 0}

    def visit(folder: str, name: str, depth: int) -> Node:
        node = Node(name=name, path=folder)
        counters["folders"] += 1
        try:
            entries = list(os.scandir(folder))
        except OSError:
            counters["denied"] += 1
            return node
        for entry in entries:
            if counters["files"] % _PROGRESS_EVERY == 0:
                ctx.cancel.raise_if_cancelled()
                ctx.progress(counters["files"], 0, folder)
            try:
                if entry.is_dir(follow_symlinks=False):
                    if _is_reparse(entry) or depth >= depth_limit:
                        continue
                    child = visit(entry.path, entry.name, depth + 1)
                    node.size += child.size
                    node.files += child.files
                    node.children.append(child)
                    continue
                info = entry.stat(follow_symlinks=False)
            except OSError:
                counters["denied"] += 1
                continue
            if not stat.S_ISREG(info.st_mode):
                continue
            size = info.st_size
            node.size += size
            node.files += 1
            counters["files"] += 1
            by_extension[Path(entry.name).suffix.lower() or "(sin extensión)"] += size
            if len(largest) < keep_files or size > largest[-1][0]:
                largest.append((size, entry.path, info.st_mtime))
                largest.sort(reverse=True)
                del largest[keep_files:]
        node.children.sort(key=lambda child: child.size, reverse=True)
        return node

    root = visit(str(path), path.name or str(path), 0)
    return Scan(
        root=root,
        largest_files=largest,
        by_extension=by_extension,
        denied=counters["denied"],
        files=counters["files"],
        folders=counters["folders"],
        elapsed_s=time.monotonic() - started,
    )


def folder_size(path: Path, ctx: ToolContext, budget_s: float) -> int | None:
    """Tamaño real de una carpeta con presupuesto de tiempo; None si no alcanzó."""
    deadline = time.monotonic() + budget_s
    total = 0
    stack = [str(path)]
    while stack:
        if time.monotonic() > deadline:
            return None
        ctx.cancel.raise_if_cancelled()
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if not _is_reparse(entry):
                        stack.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
    return total


def iter_files(
    path: Path, ctx: ToolContext, *, recursive: bool = True, pattern: str = "*"
) -> Iterator[tuple[Path, os.stat_result]]:
    """Archivos normales con su información; las carpetas sin permiso se omiten en silencio."""
    stack = [str(path)]
    count = 0
    while stack:
        try:
            entries = list(os.scandir(stack.pop()))
        except OSError:
            continue
        for entry in entries:
            count += 1
            if count % _PROGRESS_EVERY == 0:
                ctx.cancel.raise_if_cancelled()
            try:
                if entry.is_dir(follow_symlinks=False):
                    if recursive and not _is_reparse(entry):
                        stack.append(entry.path)
                    continue
                if not fnmatch.fnmatch(entry.name.lower(), pattern.lower()):
                    continue
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                yield Path(entry.path), info


def is_folder(path: Path) -> bool:
    """Como Path.is_dir, pero una carpeta sin permiso cuenta como inexistente en vez de fallar."""
    try:
        return path.is_dir()
    except OSError:
        return False


def chart_nodes(
    node: Node, depth: int, *, max_children: int = 25, min_share: float = 0.002
) -> dict[str, object]:
    """Árbol para el gráfico: lo pequeño se agrupa en «Otros» para que sea legible."""
    data: dict[str, object] = {"name": node.name, "value": node.size, "path": node.path}
    if not node.children:
        return data
    if depth <= 0:
        # Tiene subcarpetas que este nivel ya no muestra: la interfaz ofrece analizarla aparte.
        data["more"] = True
        return data
    threshold = node.size * min_share
    shown = [c for c in node.children[:max_children] if c.size >= threshold and c.size > 0]
    rest = node.size - sum(c.size for c in shown)
    children = [
        chart_nodes(c, depth - 1, max_children=max_children, min_share=min_share) for c in shown
    ]
    if rest > threshold and rest > 0:
        children.append(
            {"name": "Archivos y otras carpetas", "value": rest, "path": node.path, "group": True}
        )
    if children:
        data["children"] = children
    return data

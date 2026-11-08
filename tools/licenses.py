"""Licencias de lo que viaja en el ejecutable: valida la política y genera el aviso a terceros."""

from __future__ import annotations

import importlib.metadata as metadata
import json
import re
from dataclasses import dataclass
from pathlib import Path

ROOTS = ("starlette", "uvicorn", "pydantic")
UI = Path(__file__).resolve().parents[1] / "ui"
# Copyleft: exigiría obligaciones incompatibles con un ejecutable propietario de un solo archivo.
FORBIDDEN_LICENSE = re.compile(r"\b([al]?gpl|gnu (lesser |affero )?general public)", re.IGNORECASE)
# Requisito del producto: sin telemetría, ni siquiera inactiva.
FORBIDDEN_PACKAGES = re.compile(r"(opentelemetry|sentry|datadog|telemetry|posthog)", re.IGNORECASE)


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    license: str
    license_text: str


def _normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _license_of(distribution: metadata.Distribution) -> str:
    info = distribution.metadata
    expression = info.get("License-Expression")
    if expression:
        return str(expression)
    classifiers = [
        value.split("::")[-1].strip()
        for value in info.get_all("Classifier", []) or []
        if value.startswith("License ::")
    ]
    if classifiers:
        return ", ".join(classifiers)
    return str(info.get("License") or "Sin declarar").split("\n")[0][:80]


def _license_text(distribution: metadata.Distribution) -> str:
    texts = [
        Path(str(distribution.locate_file(file))).read_text(encoding="utf-8", errors="replace")
        for file in distribution.files or []
        if ".dist-info" in str(file)
        and re.search(r"(licen[cs]e|copying|notice)", file.name, re.IGNORECASE)
    ]
    return "\n\n".join(texts)


def runtime_packages(roots: tuple[str, ...] = ROOTS) -> list[Package]:
    """Cierre de dependencias de ejecución, sin extras opcionales."""
    seen: dict[str, Package] = {}

    def walk(name: str) -> None:
        key = _normalized(name)
        if key in seen:
            return
        try:
            distribution = metadata.distribution(key)
        except metadata.PackageNotFoundError:
            return  # Dependencia condicionada a otra plataforma.
        seen[key] = Package(
            key, distribution.version, _license_of(distribution), _license_text(distribution)
        )
        for requirement in distribution.requires or []:
            if "extra ==" not in requirement:
                walk(re.split(r"[ ;<>=!~\[(]", requirement)[0])

    for root in roots:
        walk(root)
    return sorted(seen.values(), key=lambda package: package.name)


def ui_packages(ui: Path = UI) -> list[Package]:
    """Dependencias de ejecución de la interfaz compilada (sin las de desarrollo)."""
    modules = ui / "node_modules"
    seen: dict[str, Package] = {}

    def walk(name: str) -> None:
        if name in seen:
            return
        folder = modules / name
        try:
            manifest = json.loads((folder / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            seen[name] = Package(f"npm:{name}", "?", "Sin instalar", "")
            return
        texts = [
            path.read_text(encoding="utf-8", errors="replace")
            for path in sorted(folder.iterdir())
            if path.is_file() and re.match(r"(licen[cs]e|copying|notice)", path.name, re.I)
        ]
        license_value = manifest.get("license") or "Sin declarar"
        seen[name] = Package(
            f"npm:{name}", str(manifest.get("version", "?")), str(license_value), "\n\n".join(texts)
        )
        for dependency in manifest.get("dependencies", {}):
            walk(dependency)

    root = json.loads((ui / "package.json").read_text(encoding="utf-8"))
    for dependency in root.get("dependencies", {}):
        walk(dependency)
    return sorted(seen.values(), key=lambda package: package.name)


def policy_violations(packages: list[Package]) -> list[str]:
    problems: list[str] = []
    for package in packages:
        if FORBIDDEN_LICENSE.search(package.license):
            problems.append(f"{package.name}: licencia no permitida ({package.license})")
        if FORBIDDEN_PACKAGES.search(package.name):
            problems.append(f"{package.name}: paquete de telemetría no permitido")
        if package.license in {"Sin instalar", "Sin declarar"} and package.name.startswith("npm:"):
            problems.append(f"{package.name}: no se pudo comprobar su licencia")
    return problems


def write_notices(target: Path, packages: list[Package]) -> None:
    sections = ["Software de terceros incluido en HoneyCheck.exe", ""]
    sections += [f"- {p.name} {p.version}: {p.license}" for p in packages]
    sections += [
        "- Python: PSF-2.0",
        "- PyInstaller (cargador): GPL-2.0 con excepción para ejecutables empaquetados",
        "",
    ]
    for package in packages:
        sections += [
            "=" * 78,
            f"{package.name} {package.version}",
            "=" * 78,
            package.license_text,
            "",
        ]
    target.write_text("\n".join(sections), encoding="utf-8")

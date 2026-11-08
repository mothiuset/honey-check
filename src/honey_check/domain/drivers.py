"""Controladores: leer un archivo .inf y saber a qué aparatos de este equipo le sirve.

Solo texto: sin llamadas al sistema. Un .inf declara en [Manufacturer] sus secciones de modelos
por arquitectura (`Standard.NTamd64`) y en cada una los identificadores de hardware que atiende
(`USB\\VID_046D&PID_C53F`). Un aparato sirve si alguno de sus identificadores coincide.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date

from .peripherals import DeviceNode

# Decoraciones de arquitectura que corren en un Windows de 64 bits x86.
_ARCH = re.compile(r"^nt(amd64|x86|ia64|arm64|arm)?", re.IGNORECASE)
_STRING = re.compile(r"%([^%]+)%")


@dataclass(frozen=True)
class InfDriver:
    """Lo que dice un .inf de sí mismo y los identificadores de hardware que atiende."""

    name: str  # nombre del archivo (`oem55.inf` o el original)
    driver_class: str | None
    provider: str | None
    version: str | None
    date: date | None
    hardware_ids: frozenset[str]
    description: str | None = None  # el primer aparato que nombra, para mostrarlo
    # Nombres de los modelos que declara: en una impresora, el nombre del controlador que usa
    # Windows («HP LaserJet Pro M404-M405 PCL 6»).
    models: frozenset[str] = frozenset()


@dataclass(frozen=True)
class DriverMatch:
    driver: InfDriver
    device: DeviceNode
    # 0: identificador de hardware exacto (el mejor); 1: identificador compatible.
    rank: int


@dataclass
class _Sections:
    entries: dict[str, list[str]] = field(default_factory=dict)

    def get(self, name: str) -> list[str]:
        return self.entries.get(name.lower(), [])


def decode_inf(raw: bytes) -> str:
    """Los .inf vienen en UTF-16 con BOM, UTF-8 o la página de códigos de Windows."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _sections(text: str) -> _Sections:
    sections = _Sections()
    current: list[str] | None = None
    for raw_line in text.splitlines():
        line = _strip_comment(raw_line).strip()
        if not line:
            continue
        if line.startswith("[") and "]" in line:
            name = line[1 : line.index("]")].strip().lower()
            current = sections.entries.setdefault(name, [])
            continue
        if current is not None:
            current.append(line)
    return sections


def _strip_comment(line: str) -> str:
    """Quita el comentario (`;`) que no esté dentro de comillas."""
    quoted = False
    for index, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        elif char == ";" and not quoted:
            return line[:index]
    return line


def _key_values(lines: Iterable[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in lines:
        key, sep, value = line.partition("=")
        if sep:
            found[key.strip().lower()] = value.strip()
    return found


def _expand(value: str | None, strings: dict[str, str]) -> str | None:
    if value is None:
        return None
    expanded = _STRING.sub(lambda m: strings.get(m.group(1).lower(), m.group(0)), value)
    return expanded.strip().strip('"').strip() or None


def _runs_on_x64(decoration: str) -> bool:
    """Una sección sin decoración, NT o NTamd64 sirve en x64; NTx86, NTarm64 o NTia64 no."""
    if not decoration:
        return True
    match = _ARCH.match(decoration)
    if not match:
        return False
    arch = (match.group(1) or "").lower()
    return arch in ("", "amd64")


def _model_sections(manufacturer: list[str]) -> list[str]:
    names: list[str] = []
    for line in manufacturer:
        _, sep, value = line.partition("=")
        parts = [part.strip() for part in (value if sep else line).split(",") if part.strip()]
        if not parts:
            continue
        base, decorations = parts[0], parts[1:]
        if not decorations:
            names.append(base)
        names.extend(f"{base}.{d}" for d in decorations if _runs_on_x64(d))
    return names


def _date(raw: str | None) -> date | None:
    match = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw or "")
    if not match:
        return None
    month, day, year = (int(group) for group in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_inf(name: str, text: str) -> InfDriver:
    sections = _sections(text)
    strings = {key: value.strip('"') for key, value in _key_values(sections.get("strings")).items()}
    version = _key_values(sections.get("version"))
    driver_ver = (version.get("driverver") or "").split(",")
    ids: set[str] = set()
    models: set[str] = set()
    description: str | None = None
    for section in _model_sections(sections.get("manufacturer")):
        for line in sections.get(section):
            label, sep, value = line.partition("=")
            if not sep:
                continue
            parts = [part.strip().upper() for part in value.split(",")[1:] if part.strip()]
            ids.update(parts)
            model = _expand(label.strip(), strings)
            if model:
                models.add(model)
            if description is None and parts:
                description = model
    return InfDriver(
        name=name,
        driver_class=_expand(version.get("class"), strings),
        provider=_expand(version.get("provider"), strings),
        version=driver_ver[1].strip() if len(driver_ver) > 1 else None,
        date=_date(driver_ver[0]),
        hardware_ids=frozenset(ids),
        description=description,
        models=frozenset(models),
    )


def matches(drivers: Sequence[InfDriver], devices: Sequence[DeviceNode]) -> list[DriverMatch]:
    """Cada aparato con el controlador que mejor le sirve (exacto antes que compatible)."""
    found: list[DriverMatch] = []
    for device in devices:
        exact = {item.upper() for item in device.hardware_ids}
        compatible = {item.upper() for item in device.compatible_ids}
        best: DriverMatch | None = None
        for driver in drivers:
            if driver.hardware_ids & exact:
                rank = 0
            elif driver.hardware_ids & compatible:
                rank = 1
            else:
                continue
            newer = (
                best is not None
                and rank == best.rank
                and (driver.date or date.min) > (best.driver.date or date.min)
            )
            if best is None or rank < best.rank or newer:
                best = DriverMatch(driver, device, rank)
        if best is not None:
            found.append(best)
    return found


# Problemas que se resuelven instalando o reinstalando el controlador.
DRIVER_PROBLEMS = frozenset({1, 3, 10, 18, 19, 21, 24, 28, 31, 32, 37, 39, 40, 41, 43, 48, 52})


def needs_driver(device: DeviceNode) -> bool:
    """Un aparato conectado sin controlador o con un problema de controlador (Windows lo marca con
    un código de problema: 28 si no tiene controlador)."""
    return device.present and device.problem_code in DRIVER_PROBLEMS


# --- Controlador de una impresora por su modelo ---------------------------------------------------

_BRANDS = {
    "hp": ("hp", "hewlett"),
    "canon": ("canon",),
    "brother": ("brother",),
    "epson": ("epson",),
    "kyocera": ("kyocera",),
    "xerox": ("xerox", "fuji xerox"),
    "ricoh": ("ricoh", "lanier", "savin"),
    "lexmark": ("lexmark",),
    "samsung": ("samsung",),
    "konica": ("konica", "minolta"),
    "sharp": ("sharp",),
    "oki": ("oki",),
    "toshiba": ("toshiba",),
    "pantum": ("pantum",),
}

# Los universales de cada marca, si están instalados, antes que el genérico de Windows.
UNIVERSAL_DRIVERS = {
    "hp": ("HP Universal Printing PCL 6", "HP Universal Printing PS"),
    "canon": ("Canon Generic Plus PCL6", "Canon Generic Plus UFR II"),
    "brother": ("Brother Mono Universal Printer (PCL)", "Brother Universal Printer"),
    "kyocera": ("Kyocera Classic Universaldriver PCL6", "KX DRIVER for Universal Printing"),
    "xerox": ("Xerox Global Print Driver PCL6",),
    "ricoh": ("PCL6 Driver for Universal Print", "RICOH PCL6 UniversalDriver V4.30"),
    "lexmark": ("Lexmark Universal v2", "Lexmark Universal v2 XL"),
    "samsung": ("Samsung Universal Print Driver 3",),
    "epson": ("EPSON Universal Print Driver",),
    "konica": ("KONICA MINOLTA Universal PCL",),
}

# Controladores de clase que trae Windows: imprimen en casi cualquier impresora láser de red.
GENERIC_DRIVERS = (
    "Microsoft PCL6 Class Driver",
    "Microsoft PS Class Driver",
    "Microsoft IPP Class Driver",
)

_TOKEN = re.compile(r"[a-z0-9]+")


def printer_brand(model: str | None) -> str | None:
    lowered = (model or "").lower()
    for brand, names in _BRANDS.items():
        if any(re.search(r"\b" + re.escape(name) + r"\b", lowered) for name in names):
            return brand
    return None


def _model_tokens(text: str) -> set[str]:
    return {token for token in _TOKEN.findall(text.lower()) if any(c.isdigit() for c in token)}


def _numbers_match(model: str, driver: str) -> int:
    """Cuántos números de modelo coinciden («m404dn» con «m404», «mfp m428» con «m428-m429»)."""
    wanted = _model_tokens(model)
    offered = _model_tokens(driver)
    hits = 0
    for token in wanted:
        stem = token.rstrip("abcdefghijklmnopqrstuvwxyz") or token
        if any(
            o == token or o.startswith(stem) or stem.startswith(o) for o in offered if len(o) >= 3
        ):
            hits += 1
    return hits


def best_printer_driver(model: str | None, names: Iterable[str]) -> str | None:
    """El controlador cuyo nombre corresponde al modelo de la impresora, o None.

    Exige la misma marca y al menos un número de modelo en común; entre varios, el que más
    números y palabras comparte, y PCL 6 antes que otros lenguajes.
    """
    if not model:
        return None
    brand = printer_brand(model)
    words = set(_TOKEN.findall(model.lower()))
    best: tuple[int, int, int, str] | None = None
    for name in names:
        if brand and printer_brand(name) != brand:
            continue
        numbers = _numbers_match(model, name)
        if not numbers:
            continue
        shared = len(words & set(_TOKEN.findall(name.lower())))
        pcl6 = 1 if re.search(r"pcl\s?6", name, re.IGNORECASE) else 0
        score = (numbers, shared, pcl6, name)
        if best is None or score[:3] > best[:3]:
            best = score
    return best[3] if best else None

"""Entrada del ejecutable: los imports absolutos no funcionan desde `honey_check/__main__.py`."""

import ctypes
import json
import multiprocessing
import sys
from pathlib import Path

_EXIT_COMPONENTS_MISMATCH = 3
_MB_ICONERROR = 0x10
_COMPONENTS_MARKER = "huella-componentes.txt"
_MISMATCH = (
    "Este HoneyCheck.exe necesita otra versión de la carpeta «componentes».\n\n"
    "Descargue una vez la carpeta completa (HoneyCheck-experimental.zip) y reemplace la de la USB; "
    "las siguientes actualizaciones vuelven a ser solo HoneyCheck.exe."
)


def components_match() -> bool:
    """Se actualiza solo el .exe: antes de cargar nada más, `componentes\\` debe corresponderle."""
    try:
        from honey_check import _bundle
    except ImportError:  # Sin empaquetar.
        return True
    marker = Path(sys._MEIPASS) / _COMPONENTS_MARKER  # type: ignore[attr-defined]
    try:
        return bool(marker.read_text(encoding="utf-8").strip() == _bundle.COMPONENTS)
    except OSError:
        return False


def report_mismatch(argv: list[str]) -> None:
    # Las pruebas de empaquetado pasan --status-file: ahí no puede quedar un aviso esperando.
    if "--status-file" in argv[:-1]:
        status_file = Path(argv[argv.index("--status-file") + 1])
        status_file.write_text(json.dumps({"error": "components_mismatch"}), encoding="utf-8")
        return
    ctypes.windll.user32.MessageBoxW(None, _MISMATCH, "Honey Check", _MB_ICONERROR)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    if not components_match():
        report_mismatch(sys.argv)
        sys.exit(_EXIT_COMPONENTS_MISMATCH)

    from honey_check.app import main

    sys.exit(main())

"""Compila Honey Check y deja en `dist\\HoneyCheck` solo la compilación nueva, lista para usar.

    compilar.cmd                 (doble clic, o desde la terminal en experiments\\honey-check)
    compilar.cmd --sin-abrir     sin abrir el Explorador al terminar

Las protecciones de la carpeta están en `build.py` (también las usa `publish.py`): una sola
compilación a la vez, nada se toca si Honey Check está abierto desde ahí, la carpeta anterior
vuelve si algo falla y `HoneyCheck-datos` (inventarios, respaldos, registros) pasa a la nueva.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTABLE = ROOT / "dist" / "HoneyCheck"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sin-abrir", action="store_true", help="no abrir el Explorador")
    args = parser.parse_args()

    print("Compilando Honey Check (interfaz y ejecutable)…", flush=True)
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(ROOT / "tools" / "build.py"), "--sin-zip"], cwd=ROOT, check=False
    )
    if result.returncode != 0:
        return result.returncode

    manifest = json.loads((PORTABLE / "build-manifest.json").read_text(encoding="utf-8"))
    print(
        f"\nListo: {PORTABLE}\n"
        f"  Compilación {manifest['build']}, commit {manifest['commit'][:7]}"
        f"{' con cambios sin commit' if manifest.get('localChanges') else ''}\n"
        "  La app muestra lo mismo abajo en el menú lateral.\n"
        "  Para una USB, copie la carpeta HoneyCheck completa."
    )
    if not args.sin_abrir:
        os.startfile(PORTABLE)  # type: ignore[attr-defined]  # noqa: S606
    return 0


if __name__ == "__main__":
    sys.exit(main())

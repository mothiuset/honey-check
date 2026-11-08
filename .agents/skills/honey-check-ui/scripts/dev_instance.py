"""Instancia de prueba de Honey Check para revisar la interfaz con capturas.

Usa otro nombre de instancia única, así no choca con el Honey Check que el técnico tenga abierto,
y escribe sus datos en --output-dir (una carpeta temporal, nunca el repositorio). Cada vez que
aparece <output-dir>/pedir, escribe en <output-dir>/entrada.txt una URL de entrada nueva: el boleto
de sesión sirve una sola vez.

    uv run --frozen python .agents/skills/honey-check-ui/scripts/dev_instance.py --output-dir %TEMP%\\hc-dev
"""

import sys
import threading
import time
from pathlib import Path

from honey_check import app
from honey_check.infrastructure.windows.instance import SingleInstance

args = app._parse_args([*sys.argv[1:], "--no-browser", "--no-tray"])  # noqa: SLF001
if args.output_dir is None:
    raise SystemExit("Indique --output-dir con una carpeta temporal")
folder = Path(args.output_dir)
folder.mkdir(parents=True, exist_ok=True)
app.configure_logging(folder / "HoneyCheck-datos")
instance = SingleInstance("HoneyCheck-revision-ui")
if not instance.acquire():
    raise SystemExit("Ya hay una instancia de prueba abierta")
application = app.Application(args, instance)


def tickets() -> None:
    while True:
        request = folder / "pedir"
        if request.exists():
            request.unlink()
            (folder / "entrada.txt").write_text(application.entry_url(), encoding="utf-8")
        time.sleep(0.1)


threading.Thread(target=tickets, daemon=True).start()
print(f"Instancia de prueba lista; datos en {folder}", flush=True)
sys.exit(application.run())

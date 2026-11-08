"""Captura de una ruta de la instancia de prueba (dev_instance.py) con Edge.

    uv run --frozen python .agents/skills/honey-check-ui/scripts/shot.py "#soporte?tool=disk.analyze&path=C%3A%5C&auto=1" salida.png
        [--dir %TEMP%\\hc-dev] [--width 1280] [--light] [--wait 1500] [--do "page.get_by_role('button', name='X').click()"]

--do ejecuta código de Playwright sobre `page` (con `re` disponible) antes de capturar; se puede repetir.
"""

import argparse
import os
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument("route", help="ruta con #, por ejemplo #soporte?tool=disk.analyze")
parser.add_argument("output", type=Path)
parser.add_argument("--dir", type=Path, default=Path(os.environ.get("TEMP", ".")) / "hc-dev")
parser.add_argument("--width", type=int, default=1280)
parser.add_argument("--light", action="store_true")
parser.add_argument("--wait", type=int, default=1500, help="milisegundos tras abrir la ruta")
parser.add_argument("--do", action="append", default=[], help="código de Playwright sobre page")
args = parser.parse_args()

entry_file = args.dir / "entrada.txt"
entry_file.unlink(missing_ok=True)
(args.dir / "pedir").write_text("", encoding="utf-8")
deadline = time.monotonic() + 15
while not entry_file.exists():
    if time.monotonic() > deadline:
        raise SystemExit("La instancia de prueba no respondió: ¿está abierta dev_instance.py?")
    time.sleep(0.1)
entry = entry_file.read_text(encoding="utf-8")

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="msedge")
    page = browser.new_page(
        viewport={"width": args.width, "height": 900},
        color_scheme="light" if args.light else "dark",
    )
    page.goto(entry)
    page.wait_for_load_state("networkidle")
    page.goto(entry.split("/auth/")[0] + "/" + args.route)
    page.wait_for_timeout(args.wait)
    for action in args.do:
        exec(action, {"page": page, "re": re})  # noqa: S102 - herramienta local del desarrollador
        page.wait_for_timeout(400)
    page.screenshot(path=str(args.output))
    browser.close()
print(args.output)

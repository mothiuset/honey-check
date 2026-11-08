"""Construye el ejecutable portable y deja un manifiesto con versión, commit y hash.

Una sola compilación a la vez; no toca dist\\HoneyCheck si la app está abierta desde ahí; si
falla, devuelve la carpeta anterior; HoneyCheck-datos pasa a la carpeta nueva.

`--sin-zip` omite HoneyCheck.zip: para probar en local basta la carpeta dist/HoneyCheck.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import msvcrt
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import licenses

from honey_check import __version__
from honey_check.domain.inventory import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
DIST = ROOT / "dist"
BUILD_INFO = ROOT / "src" / "honey_check" / "_build_info.py"
PORTABLE = DIST / "HoneyCheck"
EXE = PORTABLE / "HoneyCheck.exe"
ZIP = DIST / "HoneyCheck.zip"
# La escribe packaging/honey-check.spec; el .exe la compara al arrancar.
COMPONENTS_MARKER = PORTABLE / "componentes" / "huella-componentes.txt"
# PyInstaller escribe aquí; dist\HoneyCheck no se toca hasta que la compilación salió bien.
OUT = BUILD / "salida"
FRESH = OUT / "HoneyCheck"
FRESH_EXE = FRESH / "HoneyCheck.exe"
FRESH_MARKER = FRESH / "componentes" / "huella-componentes.txt"

VERSION_TEMPLATE = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, 0),
    prodvers=({a}, {b}, {c}, 0),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)
  ),
  kids=[
    StringFileInfo([StringTable('040a04b0', [
      StringStruct('FileDescription', 'Honey Check: inventario técnico portable'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'HoneyCheck'),
      StringStruct('OriginalFilename', 'HoneyCheck.exe'),
      StringStruct('ProductName', 'Honey Check'),
      StringStruct('ProductVersion', '{version}')
    ])]),
    VarFileInfo([VarStruct('Translation', [1034, 1200])])
  ]
)
"""


def _git(*args: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


def git_commit() -> str:
    return _git("rev-parse", "HEAD")


def build_number() -> int:
    """Siempre sube: la cantidad de commits de la rama. Mayor número, compilación más nueva."""
    return int(_git("rev-list", "--count", "HEAD"))


def local_changes() -> bool:
    """Cambios sin commit en Honey Check: la compilación no es exactamente la del commit."""
    return bool(_git("status", "--porcelain", "--", "."))


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_interface() -> None:
    """Compila la interfaz Vue a `presentation/web/dist`, que el ejecutable incluye."""
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if npm is None:
        raise SystemExit("Se necesita Node.js (npm) para compilar la interfaz")
    ui = ROOT / "ui"
    if not (ui / "node_modules").is_dir():
        subprocess.run([npm, "ci"], cwd=ui, check=True)  # noqa: S603
    subprocess.run([npm, "run", "build"], cwd=ui, check=True)  # noqa: S603


def write_checksums(folder: Path) -> None:
    """SHA256SUMS.txt con cada archivo de la carpeta portable, para verificarla completa."""
    lines = [
        f"{sha256_of(path)}  {path.relative_to(folder).as_posix()}"
        for path in sorted(folder.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    (folder / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_zip(folder: Path, target: Path) -> None:
    """La carpeta portable completa, lista para descomprimir en la USB."""
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, Path(folder.name) / path.relative_to(folder))


def _build(args: argparse.Namespace) -> int:
    commit = git_commit()
    number = build_number()
    modified = local_changes()
    built_at = datetime.now(UTC)
    a, b, c = (int(part) for part in __version__.split(".")[:3])
    BUILD.mkdir(exist_ok=True)
    (BUILD / "version_info.txt").write_text(
        VERSION_TEMPLATE.format(a=a, b=b, c=c, version=__version__), encoding="utf-8"
    )
    build_interface()
    packages = licenses.runtime_packages() + licenses.ui_packages()
    problems = licenses.policy_violations(packages)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    BUILD_INFO.write_text(
        f'COMMIT = "{commit}"\n'
        f"BUILD = {number}\n"
        f'BUILT_AT = "{built_at.isoformat(timespec="seconds")}"\n'
        f"LOCAL_CHANGES = {modified}\n",
        encoding="utf-8",
    )
    try:
        subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--distpath",
                str(OUT),
                "--workpath",
                str(BUILD / "pyinstaller"),
                str(ROOT / "packaging" / "honey-check.spec"),
            ],
            cwd=ROOT,
            check=True,
        )
    finally:
        BUILD_INFO.unlink(missing_ok=True)

    if not FRESH_EXE.is_file():
        print("No se generó el ejecutable", file=sys.stderr)
        return 1
    licenses.write_notices(FRESH / "THIRD_PARTY_LICENSES.txt", packages)
    digest = sha256_of(FRESH_EXE)
    (FRESH / "HoneyCheck.exe.sha256").write_text(f"{digest}  HoneyCheck.exe\n", encoding="utf-8")
    manifest = {
        "app": "honey-check",
        "version": __version__,
        "build": number,
        "commit": commit,
        "localChanges": modified,
        "schemaVersion": SCHEMA_VERSION,
        "builtAt": built_at.isoformat(),
        "sha256": digest,
        "sizeBytes": FRESH_EXE.stat().st_size,
        # Igual en dos compilaciones: basta copiar el HoneyCheck.exe nuevo sobre la carpeta.
        "componentsFingerprint": FRESH_MARKER.read_text(encoding="utf-8").strip(),
        "python": sys.version.split()[0],
    }
    (FRESH / "build-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    write_checksums(FRESH)
    if args.sin_zip:
        ZIP.unlink(missing_ok=True)
    else:
        write_zip(FRESH, ZIP)
    shutil.rmtree(BUILD / "pyinstaller", ignore_errors=True)
    print(json.dumps(manifest, indent=2))
    return 0


# --- La carpeta de salida ------------------------------------------------------------------------
# PyInstaller borraba dist\HoneyCheck entera antes de escribirla: con Honey Check abierto desde ahí
# la dejaba a medias (la app abierta quedaba rota), se llevaba sus datos, y dos compilaciones a la
# vez se pisaban. Ahora compila en build\salida; al terminar bien, cambia el contenido de
# dist\HoneyCheck archivo por archivo. La carpeta misma no se renombra (una ventana del Explorador
# o una terminal ubicada en ella lo impiden) y HoneyCheck-datos no se mueve nunca.

PREVIOUS = DIST / "HoneyCheck.anterior"
DATA = "HoneyCheck-datos"


@contextlib.contextmanager
def single_build() -> Iterator[bool]:
    """Verdadero si esta es la única compilación en curso. Windows suelta el bloqueo si el proceso
    termina de cualquier forma, así que no quedan bloqueos huérfanos."""
    BUILD.mkdir(exist_ok=True)
    with (BUILD / "compilando.lock").open("a+b") as handle:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            handle.seek(0)
            with contextlib.suppress(OSError):
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def app_running() -> bool:
    """Un .exe en ejecución no se puede abrir para escritura."""
    for exe in PORTABLE.glob("*.exe") if PORTABLE.is_dir() else []:
        try:
            with exe.open("r+b"):
                pass
        except PermissionError:
            return True
    return False


def swap_in() -> bool:
    """Cambia el contenido de dist\\HoneyCheck por la compilación nueva. Si algo de la anterior
    está en uso, la deja como estaba y devuelve False."""
    shutil.rmtree(PREVIOUS, ignore_errors=True)
    PREVIOUS.mkdir(parents=True)
    PORTABLE.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for item in sorted(PORTABLE.iterdir()):
        if item.name == DATA:
            continue
        try:
            item.rename(PREVIOUS / item.name)
        except OSError:
            for name in moved:
                (PREVIOUS / name).rename(PORTABLE / name)
            shutil.rmtree(PREVIOUS, ignore_errors=True)
            return False
        moved.append(item.name)
    for item in FRESH.iterdir():
        item.rename(PORTABLE / item.name)
    shutil.rmtree(PREVIOUS, ignore_errors=True)
    shutil.rmtree(OUT, ignore_errors=True)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sin-zip", action="store_true", help="no genera HoneyCheck.zip")
    args = parser.parse_args()
    closed = (
        f"Honey Check está abierto desde {PORTABLE}. Ciérrelo (menú de la bandeja > Salir) y "
        "vuelva a compilar. La carpeta quedó como estaba."
    )
    with single_build() as alone:
        if not alone:
            print(
                "Ya hay otra compilación en curso (compilar.cmd o publish.py). Espere a que "
                "termine: dos a la vez se pisarían.",
                file=sys.stderr,
            )
            return 2
        if app_running():
            print(closed, file=sys.stderr)
            return 2
        shutil.rmtree(OUT, ignore_errors=True)
        code = _build(args)
        if code != 0 or not FRESH_EXE.is_file():
            print("La compilación falló: dist\\HoneyCheck quedó como estaba.", file=sys.stderr)
            return code or 1
        if not swap_in():
            print(closed + f" La compilación nueva quedó en {FRESH}.", file=sys.stderr)
            return 2
        return 0


if __name__ == "__main__":
    sys.exit(main())

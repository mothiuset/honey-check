"""Compila, prueba el ejecutable y lo publica en la versión preliminar `honey-check-latest`.

Reemplaza a GitHub Actions para las descargas: todo corre en este equipo y solo se suben los
archivos a la Release (subir archivos a una Release no consume minutos de Actions ni cuesta).
Los enlaces fijos del README siguen funcionando:

    .../releases/download/honey-check-latest/HoneyCheck.exe              (actualizar una USB)
    .../releases/download/honey-check-latest/HoneyCheck-experimental.zip (primera vez)

Uso, desde la carpeta del proyecto:

    uv run python tools/publish.py              # compila, prueba el .exe y publica
    uv run python tools/publish.py --sin-pruebas  # si Honey Check está abierto en este equipo

Requiere `gh` con sesión iniciada. Publica solo un commit que ya está en GitHub, sin cambios
locales: lo descargado siempre corresponde a un commit que cualquiera puede ver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PORTABLE = DIST / "HoneyCheck"
STAGE = ROOT / "build" / "publicar"
TAG = "honey-check-latest"
REPO = "mothiuset/honey-check"
ASSETS = (
    "HoneyCheck.exe",
    "HoneyCheck.exe.sha256",
    "build-manifest.json",
    "HoneyCheck-experimental.zip",
    "HoneyCheck-experimental.zip.sha256",
)


def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, text=True, encoding="utf-8", **kwargs)  # type: ignore[call-overload,no-any-return]  # noqa: S603


def git(*args: str) -> str:
    return run(["git", *args], cwd=ROOT, capture_output=True).stdout.strip()


def gh() -> str:
    found = shutil.which("gh")
    if not found:
        raise SystemExit("Hace falta GitHub CLI (gh) con sesión iniciada")
    return found


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_published_commit() -> str:
    """El ejecutable debe corresponder a un commit que ya está en GitHub, sin cambios locales."""
    if git("status", "--porcelain", "--", "."):
        raise SystemExit("Hay cambios sin commit en la carpeta del proyecto: haga commit primero")
    git("fetch", "--quiet")
    ahead = git("rev-list", "--count", "@{upstream}..HEAD")
    if ahead != "0":
        raise SystemExit(f"Hay {ahead} commit(s) sin push: haga push primero")
    return git("rev-parse", "HEAD")


def honey_check_running() -> bool:
    output = subprocess.run(  # noqa: S603
        [r"C:\Windows\System32\tasklist.exe", "/FI", "IMAGENAME eq HoneyCheck.exe", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return "HoneyCheck.exe" in output


def build() -> dict[str, object]:
    print("Compilando…", flush=True)
    run([sys.executable, str(ROOT / "tools" / "build.py")], cwd=ROOT)
    return json.loads((PORTABLE / "build-manifest.json").read_text(encoding="utf-8"))


def test_executable() -> None:
    if honey_check_running():
        raise SystemExit(
            "Honey Check está abierto en este equipo y bloquearía las pruebas del ejecutable "
            "(instancia única). Ciérrelo o use --sin-pruebas."
        )
    print("Probando el ejecutable…", flush=True)
    env = {**os.environ, "HONEY_CHECK_EXE": str(PORTABLE / "HoneyCheck.exe")}
    run([sys.executable, "-m", "pytest", "tests/packaging", "-q"], cwd=ROOT, env=env)


def stage() -> None:
    shutil.rmtree(STAGE, ignore_errors=True)
    STAGE.mkdir(parents=True)
    for name in ("HoneyCheck.exe", "HoneyCheck.exe.sha256", "build-manifest.json"):
        shutil.copy2(PORTABLE / name, STAGE / name)
    zip_path = STAGE / "HoneyCheck-experimental.zip"
    shutil.copy2(DIST / "HoneyCheck.zip", zip_path)
    (STAGE / "HoneyCheck-experimental.zip.sha256").write_text(
        f"{sha256_of(zip_path)}  HoneyCheck-experimental.zip\n", encoding="utf-8"
    )


def published_fingerprint(tool: str) -> str | None:
    result = subprocess.run(  # noqa: S603
        [tool, "release", "download", TAG, "-R", REPO, "-p", "build-manifest.json", "-O", "-"],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return (
            json.loads(result.stdout).get("componentsFingerprint")
            if result.returncode == 0
            else None
        )
    except ValueError:
        return None


def title(manifest: dict[str, object]) -> str:
    """El título de la página de descarga dice qué compilación es: GitHub muestra la fecha en que
    se creó la versión, no la de los archivos, así que sin esto parece vieja o nueva sin serlo."""
    built = str(manifest.get("builtAt", ""))[:10]
    commit = str(manifest.get("commit", ""))[:7]
    version, build = manifest.get("version"), manifest.get("build")
    return f"Honey Check {version} · compilación {build} · {commit} · {built}"


def notes(manifest: dict[str, object], previous: str | None) -> str:
    current = manifest.get("componentsFingerprint")
    if previous and previous == current:
        how = (
            "**Actualizar una USB que ya tiene Honey Check:** descargue solo `HoneyCheck.exe` y "
            "reemplácelo en la carpeta `HoneyCheck`. Esta compilación no cambió `componentes`."
        )
    else:
        how = (
            "**Esta compilación cambió `componentes`:** descargue esta vez la carpeta completa "
            "(`HoneyCheck-experimental.zip`). Un `HoneyCheck.exe` suelto sobre la carpeta "
            "anterior avisa y no arranca."
        )
    exe = (STAGE / "HoneyCheck.exe.sha256").read_text(encoding="utf-8").split()[0]
    archive = (STAGE / "HoneyCheck-experimental.zip.sha256").read_text(encoding="utf-8").split()[0]
    return "\n".join(
        [
            f"## {title(manifest)}",
            "",
            "Compilación experimental de Honey Check, rama `experiment/honey-check`. "
            "**No es una versión estable.** La app muestra la misma compilación abajo en el menú "
            "lateral: si el número de la suya es menor, está desactualizada.",
            "",
            how,
            "",
            "**Primera vez:** `HoneyCheck-experimental.zip`. Descomprímalo en su PC y copie la "
            "carpeta `HoneyCheck` completa a la USB; abra `HoneyCheck.exe` desde ella. En el "
            "equipo que se analiza no se descomprime nada.",
            "",
            f"- Versión: {manifest.get('version')}",
            f"- Commit: `{manifest.get('commit')}`",
            "- Compilada y probada en el equipo del desarrollador (sin GitHub Actions)",
            f"- SHA-256 del ejecutable: `{exe}`",
            f"- SHA-256 del zip: `{archive}`",
            f"- Huella de `componentes`: `{current}`",
            "",
            "El ejecutable no está firmado: SmartScreen, AppLocker o WDAC pueden advertirlo o "
            "bloquearlo. Consulte `docs/testing.md` y "
            "`docs/limitations.md`.",
        ]
    )


def publish(manifest: dict[str, object]) -> None:
    tool = gh()
    previous = published_fingerprint(tool)
    notes_file = STAGE / "notas.md"
    notes_file.write_text(notes(manifest, previous), encoding="utf-8")
    print("Publicando en la versión preliminar…", flush=True)
    run(
        [
            tool, "release", "edit", TAG, "-R", REPO, "--prerelease", "--latest=false",
            "--title", title(manifest), "--notes-file", str(notes_file),
        ]
    )  # fmt: skip
    run(
        [tool, "release", "upload", TAG, "-R", REPO, "--clobber", *[str(STAGE / n) for n in ASSETS]]
    )
    listed = run(
        [tool, "release", "view", TAG, "-R", REPO, "--json", "assets", "--jq", ".assets[].name"],
        capture_output=True,
    ).stdout.split()
    for name in listed:
        if name not in ASSETS:
            run([tool, "release", "delete-asset", TAG, name, "-R", REPO, "--yes"])
    base = f"https://github.com/{REPO}/releases/download/{TAG}"
    print(f"Publicado {manifest.get('commit')}:")
    print(f"  {base}/HoneyCheck.exe")
    print(f"  {base}/HoneyCheck-experimental.zip")
    if previous and previous != manifest.get("componentsFingerprint"):
        print("Cambió `componentes`: esta vez hay que descargar el zip completo.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--sin-pruebas", action="store_true", help="no prueba el .exe compilado")
    args = parser.parse_args()
    commit = ensure_published_commit()
    manifest = build()
    if manifest.get("commit") != commit:
        raise SystemExit("La compilación no corresponde al commit actual")
    if not args.sin_pruebas:
        test_executable()
    stage()
    publish(manifest)
    return 0


if __name__ == "__main__":
    sys.exit(main())

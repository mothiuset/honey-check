# Empaquetado portable en carpeta: HoneyCheck.exe y sus componentes en `componentes\`, junto a él.
# Nada se descomprime en el equipo (a diferencia de un .exe único, que usa %TEMP%\_MEI*).
# El código y la interfaz van dentro de HoneyCheck.exe: una actualización normal solo cambia ese
# archivo. `componentes\` (Python, DLL y extensiones) lleva una huella que el .exe comprueba al
# arrancar (packaging/entrypoint.py). Lo invoca tools/build.py.
# -*- mode: python ; coding: utf-8 -*-
import hashlib
import io
import sys
import zipfile
from pathlib import Path

root = Path(SPECPATH).parent
web = root / "src" / "honey_check" / "presentation" / "web"
generated = Path(workpath) / "generado"
COMPONENTS_MARKER = "huella-componentes.txt"


def interface_archive() -> bytes:
    """La interfaz compilada (npm run build) como zip en memoria, sin compresión: el PYZ ya comprime."""
    dist = web / "dist"
    assert (dist / "index.html").is_file(), "Falta la interfaz compilada (npm run build)"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for path in sorted(dist.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(dist).as_posix())
    return buffer.getvalue()


def components_fingerprint(entries) -> str:
    """Cambia solo si cambian Python, las extensiones, las DLL o los datos de `componentes\\`."""
    digest = hashlib.sha256(sys.version.encode())
    for dest, src, _ in sorted(entries):
        digest.update(dest.encode())
        # base_library.zip se regenera en cada compilación; su contenido lo fija la versión de Python.
        if Path(dest).name != "base_library.zip":
            digest.update(Path(src).read_bytes())
    return digest.hexdigest()


analysis = Analysis(
    [str(root / "packaging" / "entrypoint.py")],
    pathex=[str(root / "src")],
    # Solo el icono de la bandeja: la interfaz va dentro del ejecutable (honey_check._bundle).
    datas=[
        (str(web / "icon.ico"), "honey_check/presentation/web"),
        (str(web / "__init__.py"), "honey_check/presentation/web"),
    ],
    hiddenimports=["honey_check._build_info"],
    excludes=[
        "tkinter", "unittest", "pydoc", "email.test", "test", "lib2to3",
        "PIL", "numpy", "playwright", "pytest", "httpx", "opentelemetry",
        "starlette.middleware.opentelemetry",
    ],
    optimize=1,
)

fingerprint = components_fingerprint(analysis.binaries + analysis.datas)
generated.mkdir(parents=True, exist_ok=True)
bundle_module = generated / "_bundle.py"
bundle_module.write_text(
    f"COMPONENTS = {fingerprint!r}\nINTERFACE = {interface_archive()!r}\n", encoding="utf-8"
)
marker = generated / COMPONENTS_MARKER
marker.write_text(fingerprint + "\n", encoding="utf-8")
analysis.pure.append(("honey_check._bundle", str(bundle_module), "PYMODULE-1"))

bundle = PYZ(analysis.pure)
executable = EXE(
    bundle,
    analysis.scripts,
    exclude_binaries=True,
    name="HoneyCheck",
    icon=str(web / "icon.ico"),
    version=str(root / "build" / "version_info.txt"),
    console=False,
    # UPX empeora la detección heurística de antivirus y no compensa el ahorro.
    upx=False,
    strip=False,
    debug=False,
    # Sin manifiesto de elevación: arranca con los permisos del usuario y solo pide los de
    # administrador cuando el técnico elige «Ejecutar como administrador».
    uac_admin=False,
    contents_directory="componentes",
)
COLLECT(
    executable,
    analysis.binaries,
    analysis.datas + [(COMPONENTS_MARKER, str(marker), "DATA")],
    name="HoneyCheck",
    upx=False,
    strip=False,
)

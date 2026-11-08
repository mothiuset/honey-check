# Guía para desarrollar

Requisitos: Windows 10 u 11, [uv](https://docs.astral.sh/uv/) y Edge o Chrome para las pruebas de
interfaz. uv instala Python 3.12 y las versiones exactas de `uv.lock`.

```powershell
uv sync --frozen
uv run python -m honey_check --output-dir "$env:TEMP\honey-check-dev"
```

`--output-dir` evita que los inventarios y logs de su equipo queden en el repositorio. Por si acaso,
`.gitignore` excluye `honey-check_*.json` y `logs/`.

| Opción | Uso |
| --- | --- |
| `--output-dir` | Carpeta de inventarios y logs |
| `--no-browser` | No abre el navegador |
| `--no-tray` | Sin icono de bandeja |
| `--status-file` | Pruebas de empaquetado: escribe la URL de entrada |

## Comprobaciones

```powershell
uv run ruff check src tests tools
uv run ruff format --check src tests tools
uv run mypy
uv run pytest tests/unit tests/integration   # con mocks
uv run pytest tests/windows                  # contra este Windows
uv run pytest tests/e2e                      # navegador real
```

`HONEY_CHECK_SCREENSHOTS=<carpeta>` guarda capturas de las pruebas de interfaz, que usan datos
ficticios. Para el ejecutable, consulte la [guía de compilación](build.md).

## Reglas

- Los datos de prueba son ficticios: ningún fixture proviene de un inventario real.
- Una consulta WMI es una constante del código. La API HTTP nunca aporta consultas ni comandos.
- Los scripts de PowerShell deben funcionar en Constrained Language y reciben datos por stdin.
- La interfaz usa `textContent`, nunca `innerHTML`: lo que viene del Registro no es de confianza.
- Si cambia un modelo del dominio, ejecute `uv run python tools/write_schema.py`. Un cambio
  incompatible exige subir la versión del esquema y añadir una migración.
- Ninguna excepción de un módulo llega al JSON con su mensaje: puede arrastrar rutas o seriales.
- Una dependencia de ejecución nueva debe tener licencia permisiva y no incluir telemetría.
- El icono se genera con `tools/make_icon.py`. Pillow es solo de desarrollo.

`tests/unit/test_policy.py` comprueba sobre el código varias de estas reglas.

@echo off
rem Compila Honey Check y deja solo la compilacion nueva en dist\HoneyCheck.
rem Doble clic, o desde la terminal: compilar.cmd [--sin-abrir]
setlocal
cd /d "%~dp0"
where uv >nul 2>nul || (
  echo Falta uv: instalelo desde https://docs.astral.sh/uv/ y vuelva a intentar.
  pause
  exit /b 1
)
uv run python tools\compilar.py %*
if errorlevel 1 (
  pause
  exit /b 1
)

@echo off
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/
  pause
  exit /b 1
)

uv sync --frozen --no-dev
if errorlevel 1 (
  echo Dependency installation failed.
  pause
  exit /b 1
)
uv run --frozen --no-dev python app.py

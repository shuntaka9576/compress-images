@echo off
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/
  pause
  exit /b 1
)

uv sync --frozen --all-groups
if errorlevel 1 (
  echo Dependency installation failed.
  pause
  exit /b 1
)

uv run --frozen pyinstaller --noconfirm --clean --onefile --windowed ^
  --name ImageCompressor ^
  --icon=assets\app-icon.ico ^
  --add-data "assets\app-icon.png;assets" ^
  --collect-all pillow_heif ^
  --additional-hooks-dir=. ^
  app.py

if errorlevel 1 (
  echo Build failed.
  pause
  exit /b 1
)

echo.
echo Build complete: dist\ImageCompressor.exe
pause

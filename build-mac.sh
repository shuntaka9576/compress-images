#!/bin/zsh
set -euo pipefail

cd "${0:A:h}"

.venv/bin/python tools/write_build_info.py

.venv/bin/pyinstaller \
  --noconfirm \
  --clean \
  --onedir \
  --windowed \
  --name ImageCompressor \
  --osx-bundle-identifier=com.shuntaka9576.imagecompressor \
  --icon=assets/app-icon.icns \
  --add-data assets/app-icon.png:assets \
  --add-data build/build_info.json:. \
  --collect-all pillow_heif \
  --additional-hooks-dir=. \
  app.py

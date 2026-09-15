#!/bin/bash
# Build FoodOn Avoidance.app and a drag-to-Applications .dmg.
#
# Needs a Python that PyInstaller can freeze -- NOT Apple's /usr/bin/python3, which is
# a stub for the Command Line Tools and freezes badly. Homebrew's python@3.12 plus
# python-tk@3.12 is what this was built against.
#
#   brew install python@3.12 python-tk@3.12
#   /opt/homebrew/opt/python@3.12/bin/python3.12 -m venv .buildenv
#   .buildenv/bin/pip install pyinstaller
#   PY=.buildenv/bin package/build_app.sh
#
# Only the files the server reads at runtime are bundled. The vendor ontology and
# robot.jar are build-time only and stay out: 119 MB that the app never opens.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PY:-.buildenv/bin}"
APP="FoodOn Avoidance"
OUT="dist"

rm -rf build_pyi "$OUT/$APP.app" "$OUT/$APP.dmg"

"$PY/pyinstaller" \
  --noconfirm --clean --windowed \
  --name "$APP" \
  --osx-bundle-identifier com.fluxon.foodon-avoidance \
  --workpath build_pyi --distpath "$OUT" --specpath build_pyi \
  --paths "$PWD" --paths "$PWD/build" \
  --hidden-import serve \
  --add-data "$PWD/web:web" \
  --add-data "$PWD/config:config" \
  --add-data "$PWD/data/index.json:data" \
  --add-data "$PWD/data/mined-classified.json:data" \
  --add-data "$PWD/data/repairs-classified.json:data" \
  --add-data "$PWD/data/resolution-store.json:data" \
  "$PWD/package/launcher.py"

# A .dmg, not a .zip: a zip of a .app loses nothing on macOS but gives the recipient
# a loose folder in Downloads and no hint that it belongs in Applications.
STAGE="$(mktemp -d)"
cp -R "$OUT/$APP.app" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -quiet -volname "$APP" -srcfolder "$STAGE" -ov -format UDZO \
  "$OUT/$APP.dmg"
rm -rf "$STAGE"

echo
echo "  $OUT/$APP.app   $(du -sh "$OUT/$APP.app" | cut -f1)"
echo "  $OUT/$APP.dmg   $(du -sh "$OUT/$APP.dmg" | cut -f1)"

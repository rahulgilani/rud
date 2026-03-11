#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Realtime Upload & Download"
DMG_NAME="RealtimeUploadDownload"

echo "==> Checking prerequisites..."

if ! command -v python3 &>/dev/null; then
    echo "Error: python3 not found. Install from https://python.org" >&2
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
REQUIRED="3.10"
if [[ "$(printf '%s\n' "$REQUIRED" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED" ]]; then
    echo "Error: Python $REQUIRED or later required (found $PYTHON_VERSION)" >&2
    exit 1
fi

if ! command -v create-dmg &>/dev/null; then
    echo "Error: create-dmg not found."
    echo "       Install it with: brew install create-dmg" >&2
    exit 1
fi

echo "==> Setting up virtual environment..."
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "==> Cleaning previous build artifacts..."
rm -rf build dist

echo "==> Building .app bundle..."
python setup.py py2app 2>&1 | grep -v "^$"

APP_PATH="dist/${APP_NAME}.app"

if [ ! -d "$APP_PATH" ]; then
    echo "Error: .app bundle not found at: $APP_PATH" >&2
    exit 1
fi

echo "==> Creating DMG..."
create-dmg \
    --volname "$APP_NAME" \
    --window-pos 200 120 \
    --window-size 600 400 \
    --icon-size 100 \
    --icon "${APP_NAME}.app" 175 190 \
    --hide-extension "${APP_NAME}.app" \
    --app-drop-link 425 190 \
    "dist/${DMG_NAME}.dmg" \
    "$APP_PATH"

echo ""
echo "Build complete!"
echo "  .app  ->  $APP_PATH"
echo "  .dmg  ->  dist/${DMG_NAME}.dmg"

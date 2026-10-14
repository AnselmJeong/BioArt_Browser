#!/usr/bin/env bash
set -euo pipefail
MODE="${1:-run}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
APP_BUNDLE="$ROOT_DIR/dist/BioArt Browser.app"
UV_BIN="${BIOART_UV:-$(command -v uv)}"
BUN_BIN="${BIOART_BUN:-$(command -v bun)}"
"$UV_BIN" sync --frozen --python 3.12
"$BUN_BIN" install --frozen-lockfile
if [ ! -f data/catalog/catalog.sqlite ]; then "$UV_BIN" run bioart inventory; fi
"$ROOT_DIR/script/editor_validation.sh" --clean
"$BUN_BIN" run build:editor
mkdir -p build dist
cargo build --locked --release --manifest-path native/publication/Cargo.toml
"$UV_BIN" run pyinstaller --noconfirm --clean --name bioart-backend --onedir --paths src --add-data "web:web" --add-binary "native/publication/target/release/bioart-publication:publication" --collect-all resvg_py --hidden-import bioart.server --hidden-import bioart.pipeline --hidden-import bioart.mcp_server script/backend_entry.py > build/packaging.log 2>&1
"$UV_BIN" run python -c 'import json,pathlib; pathlib.Path("build/desktop-workspace.json").write_text(json.dumps({"workspace":str(pathlib.Path.cwd())}))'
"$BUN_BIN" x electrobun prepare --env=stable
"$BUN_BIN" run typecheck
"$BUN_BIN" x electrobun build --env=stable > build/electrobun.log 2>&1
BUILT_APP="$ROOT_DIR/build/stable-macos-arm64/BioArt Browser.app"
if [ ! -d "$BUILT_APP" ]; then echo "Electrobun output not found; see build/electrobun.log"; exit 1; fi
# Keep the previous runnable bundle until the replacement is fully staged.
STAGED_APP="$ROOT_DIR/dist/.BioArt Browser.next.app"
rm -rf "$STAGED_APP"
# Stable output is a self-extracting installer. Its cross-volume rename can
# fail on external disks; distribute the real app bundle, already unpacked.
UNPACK_DIR="$(mktemp -d "$ROOT_DIR/build/desktop-unpack.XXXXXX")"
ARCHIVE="$(find "$BUILT_APP/Contents/Resources" -maxdepth 1 -name '*.tar.zst' -print -quit)"
if [ -n "$ARCHIVE" ]; then
  /usr/bin/tar -xf "$ARCHIVE" -C "$UNPACK_DIR"
  ditto "$UNPACK_DIR/BioArt Browser.app" "$STAGED_APP"
else
  ditto "$BUILT_APP" "$STAGED_APP"
fi
rm -rf "$UNPACK_DIR"
/usr/libexec/PlistBuddy -c 'Add :NSRemovableVolumesUsageDescription string 선택한 볼륨의 BioArt 자료를 읽고 도해를 저장합니다.' "$STAGED_APP/Contents/Info.plist"
codesign --force --deep --sign - "$STAGED_APP" > build/signing.log 2>&1
codesign --verify --deep --strict "$STAGED_APP"
if [ -d "$APP_BUNDLE" ]; then mv "$APP_BUNDLE" "$ROOT_DIR/dist/BioArt Browser.previous.$(date +%Y%m%d%H%M%S).app"; fi
mv "$STAGED_APP" "$APP_BUNDLE"
echo "Built: $APP_BUNDLE"
case "$MODE" in
 --build-only) ;;
 --verify|run) open -n "$APP_BUNDLE" ;;
 --debug) "$APP_BUNDLE/Contents/MacOS/launcher" ;;
 --logs|--telemetry) open -n "$APP_BUNDLE"; echo 'Use 보기 → 실행 로그 보기 in the app.' ;;
 *) echo "Usage: $0 [--build-only|--verify|--debug|--logs|--telemetry]"; exit 2 ;;
esac

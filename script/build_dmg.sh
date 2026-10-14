#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Use the complete build: bundled Python backend, unpacked app and ad-hoc signing.
./script/build_and_run.sh --build-only
APP_BUNDLE="$ROOT_DIR/dist/BioArt Browser.app"
VERSION="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$APP_BUNDLE/Contents/Info.plist")"
ARCH="$(/usr/bin/lipo -archs "$APP_BUNDLE/Contents/MacOS/launcher")"
if [[ ! "$VERSION" =~ ^[a-zA-Z0-9][a-zA-Z0-9._-]*$ ]]; then
  echo "Invalid app version: $VERSION" >&2
  exit 1
fi
case "$ARCH" in
  arm64|x86_64) ;;
  "arm64 x86_64"|"x86_64 arm64") ARCH="universal" ;;
  *) echo "Unsupported app architecture: $ARCH" >&2; exit 1 ;;
esac

DMG_PATH="$ROOT_DIR/dist/BioArt Browser-${VERSION}-${ARCH}.dmg"
WORK_DIR="$(mktemp -d "$ROOT_DIR/build/dmg-stage.XXXXXX")"
MOUNT_DIR=""
MOUNTED=false
cleanup() {
  if [ "$MOUNTED" = true ]; then
    if ! /usr/bin/hdiutil detach "$MOUNT_DIR"; then
      echo "Could not detach verification volume; leaving $WORK_DIR intact." >&2
      return
    fi
  fi
  if [ -n "$MOUNT_DIR" ]; then rmdir "$MOUNT_DIR"; fi
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

# macOS can reject mount points on external volumes. Use its local temp directory.
MOUNT_DIR="$(mktemp -d "${TMPDIR:-/private/tmp}/bioart-dmg-mount.XXXXXX")"
mkdir "$WORK_DIR/contents"
/usr/bin/ditto "$APP_BUNDLE" "$WORK_DIR/contents/BioArt Browser.app"
ln -s /Applications "$WORK_DIR/contents/Applications"
/usr/bin/hdiutil create -volname "BioArt Browser" \
  -srcfolder "$WORK_DIR/contents" -format UDZO "$WORK_DIR/BioArt Browser.dmg"
/usr/bin/hdiutil verify "$WORK_DIR/BioArt Browser.dmg"
/usr/bin/hdiutil attach -readonly -nobrowse -mountpoint "$MOUNT_DIR" "$WORK_DIR/BioArt Browser.dmg"
MOUNTED=true
/usr/bin/codesign --verify --deep --strict "$MOUNT_DIR/BioArt Browser.app"
test "$(readlink "$MOUNT_DIR/Applications")" = /Applications
/usr/bin/hdiutil detach "$MOUNT_DIR"
MOUNTED=false

# Publish only after image integrity and mounted app verification succeed.
mv -f "$WORK_DIR/BioArt Browser.dmg" "$DMG_PATH"
echo "Built and verified: $DMG_PATH"

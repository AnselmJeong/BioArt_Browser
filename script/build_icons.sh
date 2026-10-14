#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p assets/BioArt.iconset
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" assets/bioart-icon.png --out "assets/BioArt.iconset/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" assets/bioart-icon.png --out "assets/BioArt.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns assets/BioArt.iconset -o assets/BioArt.icns
cp assets/BioArt.iconset/icon_128x128.png web/icon.png

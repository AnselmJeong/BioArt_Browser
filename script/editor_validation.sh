#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ "${1:-}" = "--clean" ]; then
  rm -f web/editor-validation.js web/editor-validation.html web/editor-samples.json
  exit 0
fi
bun build tests/editor/browser.ts --target browser --format esm --outfile web/editor-validation.js
cp tests/editor/validation.html web/editor-validation.html
cp tests/editor/samples.json web/editor-samples.json
printf '%s\n' 'Start uv run bioart serve --port 8766, then open http://127.0.0.1:8766/editor-validation.html' 'This creates QA documents/exports in the active workspace. Clean generated web fixtures with script/editor_validation.sh --clean.'

#!/usr/bin/env bash
# Download pinned frontend vendor assets (fonts + JS) for offline app pages.
# Re-run when bumping versions. Requires: curl.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATIC="$ROOT/frontend/src/templates/pages/static"
VENDOR="$STATIC/vendor"
FONTS="$STATIC/fonts"
CURL_OPTS=(--connect-timeout 30 --max-time 120)

mkdir -p "$VENDOR" "$FONTS" "$VENDOR/monaco-editor"

download() {
  local url="$1"
  local dest="$2"
  if [[ -f "$dest" && -s "$dest" ]]; then
    echo "  skip (exists): $(basename "$dest")"
    return 0
  fi
  echo "  fetch: $(basename "$dest")"
  curl -fsSL "${CURL_OPTS[@]}" -o "$dest" "$url"
  sleep 0.3
}

echo "==> JS libraries"
download "https://cdn.jsdelivr.net/npm/alpinejs@3.14.8/dist/cdn.min.js" "$VENDOR/alpine.min.js"
download "https://cdn.jsdelivr.net/npm/htmx.org@2.0.8/dist/htmx.min.js" "$VENDOR/htmx.min.js"
download "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.7.0/highlight.min.js" "$VENDOR/highlight.min.js"
download "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.7.0/styles/github.min.css" "$STATIC/css/highlight.github.min.css"
download "https://cdn.plot.ly/plotly-2.32.0.min.js" "$VENDOR/plotly-2.32.0.min.js"
download "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js" "$VENDOR/marked.min.js"
download "https://cdn.socket.io/4.7.2/socket.io.min.js" "$VENDOR/socket.io.min.js"
download "https://unpkg.com/@tanstack/table-core@8.11.2/build/umd/index.production.js" "$VENDOR/tanstack-table-core.umd.js"

echo "==> Monaco Editor 0.44.0"
if [[ ! -d "$VENDOR/monaco-editor/vs/base" ]]; then
  MONACO_ZIP="/tmp/monaco-editor-0.44.0.tgz"
  curl -fsSL "${CURL_OPTS[@]}" -o "$MONACO_ZIP" \
    "https://registry.npmjs.org/monaco-editor/-/monaco-editor-0.44.0.tgz"
  rm -rf /tmp/monaco-extract
  mkdir -p /tmp/monaco-extract
  tar -xzf "$MONACO_ZIP" -C /tmp/monaco-extract
  rm -rf "$VENDOR/monaco-editor/vs"
  cp -r /tmp/monaco-extract/package/min/vs "$VENDOR/monaco-editor/"
fi
download "https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.44.0/min/vs/loader.min.js" \
  "$VENDOR/monaco-editor/loader.min.js"

fontsource() {
  local pkg="$1"
  local file="$2"
  local dest="$3"
  download "https://unpkg.com/@fontsource/${pkg}@5.1.0/files/${file}" "$dest"
}

echo "==> Fonts (@fontsource via unpkg)"
for w in 300 400 500 600 700 800; do
  fontsource "plus-jakarta-sans" "plus-jakarta-sans-latin-${w}-normal.woff2" \
    "$FONTS/plus-jakarta-sans-latin-${w}-normal.woff2"
done
for w in 400 500 600; do
  fontsource "jetbrains-mono" "jetbrains-mono-latin-${w}-normal.woff2" \
    "$FONTS/jetbrains-mono-latin-${w}-normal.woff2"
done
for w in 400 600 700; do
  fontsource "fredoka" "fredoka-latin-${w}-normal.woff2" \
    "$FONTS/fredoka-latin-${w}-normal.woff2"
done
fontsource "pacifico" "pacifico-latin-400-normal.woff2" "$FONTS/pacifico-latin-400-normal.woff2"

echo "==> Material Symbols Outlined"
download "https://fonts.gstatic.com/s/materialsymbolsoutlined/v205/kJEhBvYX7BgnkSrUwT8OhrdQw4oELdPIeeII9v6oFsI.woff2" \
  "$FONTS/material-symbols-outlined.woff2"

echo "Done. Vendor assets under $STATIC"

#!/bin/sh
set -e
DEFAULT="/opt/default-config/sources.yaml"
TARGET="${SOURCES_CONFIG_PATH:-/config/sources.yaml}"
TARGET_DIR=$(dirname "$TARGET")

if [ ! -f "$TARGET" ] && [ -f "$DEFAULT" ]; then
  mkdir -p "$TARGET_DIR" 2>/dev/null || true
  if cp "$DEFAULT" "$TARGET" 2>/dev/null; then
    echo "Seeded $TARGET from bundled default config"
  else
    echo "Warning: could not write $TARGET (read-only mount?); using bundled default at runtime"
  fi
fi

exec "$@"

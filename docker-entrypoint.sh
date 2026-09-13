#!/bin/sh
set -eu

runtime_dir="${RUNTIME_DIR:-/app/runtime}"
mkdir -p "$runtime_dir/logs" "$runtime_dir/screenshots"

if [ "$(id -u)" = "0" ]; then
    chown -R app:app "$runtime_dir" 2>/dev/null || true
    exec gosu app "$@"
fi

exec "$@"

#!/bin/sh
set -eu

PROVIDER_DIR="/opt/bgutil-ytdlp-pot-provider/server"
PROVIDER_LOG="/tmp/bgutil-provider.log"

cd "$PROVIDER_DIR/node_modules"
deno run --allow-env --allow-net --allow-ffi=. --allow-read=. ../src/main.ts --host 127.0.0.1 --port 4416 >"$PROVIDER_LOG" 2>&1 &
POT_PID=$!

sleep 2
if ! kill -0 "$POT_PID" 2>/dev/null; then
  echo "BgUtils PO Token provider failed to start"
  cat "$PROVIDER_LOG" || true
  exit 1
fi

cd /app
exec uvicorn app:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1

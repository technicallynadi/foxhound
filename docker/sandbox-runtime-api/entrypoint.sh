#!/bin/sh
# Foxhound Python Sandbox Runtime Entrypoint
#
# 1. Start the upload server (receives generated files from Foxhound backend)
# 2. Upload server auto-starts the app (uvicorn/FastAPI) when files arrive
#
# Upload server: :9090 (internal)
# App server:    :8080 (public)

set -e

echo "[foxhound] Python sandbox runtime starting..."
echo "[foxhound] Python $(python3 --version)"
echo "[foxhound] Upload server: :9090 (internal)"
echo "[foxhound] App server:    :8080 (public)"

cd /app

exec python3 /app/upload_server.py

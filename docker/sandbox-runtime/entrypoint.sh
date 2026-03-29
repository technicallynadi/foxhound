#!/bin/sh
# Foxhound Sandbox Runtime Entrypoint
#
# 1. Start the upload server (receives generated files from Foxhound backend)
# 2. The upload server starts Vite automatically when files arrive
#
# The upload server runs on :9090 (internal), Vite serves on :8080 (public)

set -e

echo "[foxhound] Sandbox runtime starting..."
echo "[foxhound] Node $(node --version)"
echo "[foxhound] Upload server: :9090 (internal)"
echo "[foxhound] Vite preview:  :8080 (public)"

cd /app

# Start the upload server (this is the main process)
exec node /app/upload-server.js

"""Foxhound Python Sandbox Upload Server.

Internal HTTP API running on port 9090 that accepts generated project files
and environment variables from the Foxhound backend. Not exposed to the public.

Endpoints:
    POST /upload              — Receive gzipped tarball of project files
    POST /_foxhound/upload    — Same (accessible via Fly proxy)
    POST /env                 — Receive environment variables
    POST /_foxhound/env       — Same
    GET  /health              — Readiness check
    GET  /_foxhound/health    — Same
"""

import hmac
import io
import json
import os
import signal
import subprocess
import sys
import tarfile
from http.server import BaseHTTPRequestHandler, HTTPServer

APP_DIR = "/app"
UPLOAD_PORT = 9090
APP_PORT = 8080

app_process = None
files_received = False


def _extract_bearer(auth_header: str) -> str:
    """Return the token from an 'Authorization: Bearer <token>' header, else ''."""
    if not auth_header:
        return ""
    parts = auth_header.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return ""


def _is_authorized(headers) -> bool:
    """Constant-time check of the shared upload token.

    Fails closed: if SANDBOX_UPLOAD_TOKEN is unset/empty, no request is allowed.
    Accepts the token via 'Authorization: Bearer <token>' or 'X-Sandbox-Token'.
    """
    expected = os.environ.get("SANDBOX_UPLOAD_TOKEN", "")
    if not expected:
        return False
    presented = _extract_bearer(headers.get("Authorization", "")) or headers.get("X-Sandbox-Token", "")
    if not presented:
        return False
    return hmac.compare_digest(presented, expected)


def _safe_extract(tar: tarfile.TarFile, dest: str) -> None:
    """Extract a tarball into dest, rejecting path traversal and links.

    Raises ValueError on any member that resolves outside dest or that is a
    symlink/hardlink, before writing anything to disk.
    """
    dest_real = os.path.realpath(dest)
    for member in tar.getmembers():
        if member.issym() or member.islnk():
            raise ValueError(f"unsafe link member in archive: {member.name}")
        if os.path.isabs(member.name):
            raise ValueError(f"absolute path member in archive: {member.name}")
        target = os.path.realpath(os.path.join(dest_real, member.name))
        if target != dest_real and not target.startswith(dest_real + os.sep):
            raise ValueError(f"path traversal in archive: {member.name}")

    # Python 3.12+ data filter is a defense-in-depth backstop on top of the
    # explicit validation above (which also keeps this safe on 3.11).
    try:
        tar.extractall(path=dest, filter="data")
    except TypeError:
        tar.extractall(path=dest)


class UploadHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path in ("/upload", "/_foxhound/upload", "/env", "/_foxhound/env"):
            if not _is_authorized(self.headers):
                self._drain_body()
                self._respond(403, {"error": "Forbidden"})
                return

        if self.path in ("/upload", "/_foxhound/upload"):
            self._handle_upload()
        elif self.path in ("/env", "/_foxhound/env"):
            self._handle_env()
        else:
            self._respond(404, {"error": "Not found"})

    def do_GET(self):
        if self.path in ("/health", "/_foxhound/health"):
            self._handle_health()
        else:
            self._respond(404, {"error": "Not found"})

    def _handle_upload(self):
        global files_received
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        print(f"[upload] Receiving {len(body)} bytes...")

        try:
            buf = io.BytesIO(body)
            with tarfile.open(fileobj=buf, mode="r:gz") as tar:
                _safe_extract(tar, APP_DIR)

            files_received = True
            print("[upload] Files extracted successfully")

            # Install deps if requirements.txt was included in the upload
            req_path = os.path.join(APP_DIR, "requirements.txt")
            if os.path.exists(req_path):
                print("[upload] Installing project requirements...")
                try:
                    subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "pip",
                            "install",
                            "-r",
                            req_path,
                            "--quiet",
                            "--no-warn-script-location",
                        ],
                        cwd=APP_DIR,
                        timeout=120,
                        check=False,
                        capture_output=True,
                    )
                    print("[upload] pip install complete")
                except subprocess.TimeoutExpired:
                    print("[upload] pip install timed out (non-fatal)")

            # Start the app server
            _start_app()

            self._respond(200, {"status": "ok", "files_received": True})

        except ValueError as e:
            print(f"[upload] Rejected unsafe archive: {e}")
            self._respond(400, {"error": "Unsafe archive"})
        except Exception as e:
            print(f"[upload] Extract failed: {e}")
            self._respond(500, {"error": str(e)})

    def _handle_env(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            env_vars = json.loads(body)
            env_lines = [f"{k}={v}" for k, v in env_vars.items()]
            env_path = os.path.join(APP_DIR, ".env")
            with open(env_path, "w") as f:
                f.write("\n".join(env_lines))
            print(f"[env] Wrote .env with {len(env_vars)} vars")
            self._respond(200, {"status": "ok"})
        except Exception as e:
            self._respond(400, {"error": str(e)})

    def _handle_health(self):
        self._respond(
            200,
            {
                "status": "ok",
                "files_received": files_received,
                "app_running": app_process is not None and app_process.poll() is None,
            },
        )

    def _drain_body(self):
        """Consume any request body so the connection can be reused/closed cleanly."""
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length > 0:
            self.rfile.read(content_length)

    def _respond(self, code: int, body: dict):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def log_message(self, format, *args):
        # Quieter logging
        pass


def _start_app():
    """Start (or restart) the application server."""
    global app_process

    if app_process and app_process.poll() is None:
        print("[app] Killing existing app process...")
        app_process.terminate()
        try:
            app_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            app_process.kill()

    # Detect what to run based on files present
    main_py = os.path.join(APP_DIR, "main.py")
    app_py = os.path.join(APP_DIR, "app.py")
    server_py = os.path.join(APP_DIR, "server.py")

    if os.path.exists(main_py):
        # FastAPI / uvicorn
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "main:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(APP_PORT),
            "--reload",
        ]
    elif os.path.exists(app_py):
        # Generic Python app
        cmd = [sys.executable, "app.py"]
    elif os.path.exists(server_py):
        # MCP or other server
        cmd = [sys.executable, "server.py"]
    else:
        # Try to find any Python file with FastAPI
        for fname in os.listdir(APP_DIR):
            if fname.endswith(".py"):
                full = os.path.join(APP_DIR, fname)
                with open(full) as f:
                    content = f.read()
                if "FastAPI" in content or "app = " in content:
                    module = fname.replace(".py", "")
                    cmd = [
                        sys.executable,
                        "-m",
                        "uvicorn",
                        f"{module}:app",
                        "--host",
                        "0.0.0.0",
                        "--port",
                        str(APP_PORT),
                        "--reload",
                    ]
                    break
        else:
            print("[app] No recognizable entry point found. Skipping app start.")
            return

    print(f"[app] Starting: {' '.join(cmd)}")
    app_process = subprocess.Popen(
        cmd,
        cwd=APP_DIR,
        env={**os.environ, "PORT": str(APP_PORT)},
    )


def main():
    print(f"[foxhound] Python sandbox upload server on :{UPLOAD_PORT}")
    print(f"[foxhound] App server will run on :{APP_PORT}")
    print(f"[foxhound] Python {sys.version}")
    print("[foxhound] Waiting for files...")

    server = HTTPServer(("0.0.0.0", UPLOAD_PORT), UploadHandler)

    def shutdown(signum, frame):
        print("[foxhound] Shutting down...")
        if app_process and app_process.poll() is None:
            app_process.terminate()
        server.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    server.serve_forever()


if __name__ == "__main__":
    main()

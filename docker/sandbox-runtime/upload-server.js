/**
 * Foxhound Sandbox Upload Server
 *
 * Internal HTTP API running on port 9090 that accepts generated project files
 * and environment variables from the Foxhound backend. Not exposed to the public.
 *
 * Endpoints:
 *   POST /upload          — Receive gzipped tarball of project files
 *   POST /_foxhound/upload — Same as above (accessible via Fly proxy)
 *   POST /env             — Receive environment variables
 *   POST /_foxhound/env   — Same as above
 *   GET  /health          — Readiness check
 *   GET  /_foxhound/health — Same as above
 */

import { createServer } from "node:http";
import { createWriteStream, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { execSync, spawn } from "node:child_process";
import { pipeline } from "node:stream/promises";
import { createGunzip } from "node:zlib";
import { extract } from "tar";

const UPLOAD_PORT = 9090;
const APP_DIR = "/app";
const SRC_DIR = "/app/src";
const VITE_PORT = 8080;

let viteProcess = null;
let filesReceived = false;

/**
 * Extract uploaded tarball into the app source directory.
 */
async function handleUpload(req, res) {
  console.log("[upload] Receiving files...");

  // Ensure src directory exists
  mkdirSync(SRC_DIR, { recursive: true });

  try {
    // Pipe request body through gunzip and tar extract
    await pipeline(
      req,
      createGunzip(),
      extract({ cwd: APP_DIR, strip: 0 })
    );

    filesReceived = true;
    console.log("[upload] Files extracted successfully");

    // Install any new dependencies if package.json was included
    if (existsSync(`${APP_DIR}/package.json`)) {
      console.log("[upload] Running npm install for new deps...");
      try {
        execSync("npm install --prefer-offline --no-audit --no-fund", {
          cwd: APP_DIR,
          stdio: "pipe",
          timeout: 60000,
        });
        console.log("[upload] npm install complete");
      } catch (e) {
        console.warn("[upload] npm install warning:", e.message?.slice(0, 200));
      }
    }

    // Start or restart Vite
    startVite();

    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "ok", files_received: true }));
  } catch (err) {
    console.error("[upload] Extract failed:", err.message);
    res.writeHead(500, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ error: err.message }));
  }
}

/**
 * Write environment variables to .env file.
 */
function handleEnv(req, res) {
  let body = "";
  req.on("data", (chunk) => (body += chunk));
  req.on("end", () => {
    try {
      const vars = JSON.parse(body);
      const envContent = Object.entries(vars)
        .map(([k, v]) => `${k}=${v}`)
        .join("\n");
      writeFileSync(`${APP_DIR}/.env`, envContent);
      console.log("[env] Wrote .env with", Object.keys(vars).length, "vars");
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "ok" }));
    } catch (err) {
      res.writeHead(400, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: err.message }));
    }
  });
}

/**
 * Health check endpoint.
 */
function handleHealth(req, res) {
  res.writeHead(200, { "Content-Type": "application/json" });
  res.end(
    JSON.stringify({
      status: "ok",
      files_received: filesReceived,
      vite_running: viteProcess !== null && viteProcess.exitCode === null,
    })
  );
}

/**
 * Start (or restart) the Vite dev server.
 */
function startVite() {
  if (viteProcess && viteProcess.exitCode === null) {
    console.log("[vite] Killing existing Vite process...");
    viteProcess.kill("SIGTERM");
  }

  console.log("[vite] Starting Vite dev server on port", VITE_PORT);
  viteProcess = spawn("npx", ["vite", "--host", "0.0.0.0", "--port", String(VITE_PORT)], {
    cwd: APP_DIR,
    stdio: "inherit",
    env: { ...process.env, NODE_ENV: "development" },
  });

  viteProcess.on("error", (err) => {
    console.error("[vite] Failed to start:", err.message);
  });

  viteProcess.on("exit", (code) => {
    console.log("[vite] Exited with code", code);
    viteProcess = null;
  });
}

/**
 * Route handler.
 */
const server = createServer((req, res) => {
  const url = req.url;
  const method = req.method;

  // Upload endpoints (internal + Fly proxy paths)
  if ((url === "/upload" || url === "/_foxhound/upload") && method === "POST") {
    return handleUpload(req, res);
  }

  // Env endpoints
  if ((url === "/env" || url === "/_foxhound/env") && method === "POST") {
    return handleEnv(req, res);
  }

  // Health endpoints
  if ((url === "/health" || url === "/_foxhound/health") && method === "GET") {
    return handleHealth(req, res);
  }

  // 404
  res.writeHead(404, { "Content-Type": "application/json" });
  res.end(JSON.stringify({ error: "Not found" }));
});

server.listen(UPLOAD_PORT, "0.0.0.0", () => {
  console.log(`[foxhound] Upload server listening on :${UPLOAD_PORT}`);
  console.log(`[foxhound] Waiting for files...`);
});

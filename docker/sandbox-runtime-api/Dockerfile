# Foxhound Python Sandbox Runtime
#
# Base image for Python preview VMs. Pre-installs FastAPI, SQLModel,
# uvicorn, Typer, Rich, MCP SDK, and other common deps so generated
# code boots instantly.
#
# Covers form factors: api_service, webhook, cli_tool, agent_skill
#
# Build: docker build -t registry.fly.io/foxhound-sandbox-api:latest .
# Push:  docker push registry.fly.io/foxhound-sandbox-api:latest

FROM python:3.12-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    tar \
    gzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pre-install the locked dependency set
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Upload server (receives files from Foxhound backend)
COPY upload_server.py ./

# Default placeholder app (replaced by uploaded code)
RUN echo 'from fastapi import FastAPI\napp = FastAPI()\n\n@app.get("/")\ndef root():\n    return {"status": "waiting", "message": "Foxhound preview — waiting for code..."}' > main.py

# Entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose ports: 8080 = app server (public), 9090 = upload API (internal)
EXPOSE 8080 9090

ENTRYPOINT ["/entrypoint.sh"]

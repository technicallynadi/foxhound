# Foxhound Sandbox Runtime
#
# Base image for all preview VMs. Pre-installs the locked web stack
# (React, Vite, Tailwind, shadcn/ui, Supabase client) so generated
# code can boot instantly without npm install.
#
# Build: docker build -t registry.fly.io/foxhound-sandbox:latest .
# Push:  docker push registry.fly.io/foxhound-sandbox:latest

FROM node:22-slim

# System deps for better-sqlite3 native build
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    make \
    g++ \
    tar \
    gzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install the locked dependency set
COPY package.json ./
RUN npm install --prefer-offline --no-audit --no-fund \
    && npm cache clean --force

# Default Vite config (overridden if generated code includes one)
COPY vite.config.ts ./
COPY tsconfig.json ./
COPY tsconfig.app.json ./
COPY tailwind.config.ts ./
COPY postcss.config.js ./
COPY index.html ./

# Default src placeholder (replaced by uploaded code)
RUN mkdir -p src && echo 'export default function App() { return <div className="flex items-center justify-center min-h-screen bg-zinc-950 text-white"><p>Waiting for code...</p></div> }' > src/App.tsx \
    && echo 'import React from "react"; import ReactDOM from "react-dom/client"; import App from "./App"; import "./index.css"; ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>)' > src/main.tsx \
    && echo '@tailwind base; @tailwind components; @tailwind utilities;' > src/index.css

# Upload server (receives files from Foxhound backend)
COPY upload-server.js ./

# Entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Expose ports: 8080 = Vite preview (public), 9090 = upload API (internal)
EXPOSE 8080 9090

ENTRYPOINT ["/entrypoint.sh"]

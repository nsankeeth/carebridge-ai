#!/usr/bin/env bash
# Start the Next.js frontend on :3000 (proxies /api to the backend).
set -euo pipefail
cd "$(dirname "$0")/../frontend"
exec npm run dev -- --port 3000

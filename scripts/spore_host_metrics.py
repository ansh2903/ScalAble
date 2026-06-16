#!/usr/bin/env python3
"""
Lightweight host metrics HTTP bridge for Spore on Docker Desktop (Windows/macOS).

Run on the physical host (not inside the Spore container):

    python scripts/spore_host_metrics.py --port 8765

Then point the Spore container at the bridge:

    SPORE_HOST_METRICS_URL=http://host.docker.internal:8765/metrics
    SPORE_HOST_METRICS_TOKEN=optional-shared-secret

The bridge binds to 0.0.0.0 by default so Docker can reach it via host.docker.internal.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

try:
    import psutil
except ImportError:
    print("psutil is required: pip install psutil", file=sys.stderr)
    sys.exit(1)


def collect_metrics() -> dict[str, Any]:
    mem = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory": {
            "used": mem.used,
            "total": mem.total,
            "percent": mem.percent,
        },
        "platform": platform.system(),
        "scope": "host",
    }


class MetricsHandler(BaseHTTPRequestHandler):
    token: str = ""

    def _authorized(self) -> bool:
        if not self.token:
            return True
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {self.token}":
            return True
        return self.headers.get("X-Spore-Metrics-Token", "") == self.token

    def do_GET(self) -> None:
        if self.path.rstrip("/") not in ("/metrics", ""):
            self.send_response(404)
            self.end_headers()
            return

        if not self._authorized():
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":"unauthorized"}')
            return

        payload = collect_metrics()
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        if os.getenv("SPORE_HOST_METRICS_QUIET", "").lower() in ("1", "true", "yes"):
            return
        super().log_message(format, *args)


def main() -> None:
    parser = argparse.ArgumentParser(description="Spore host metrics bridge")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8765, help="Listen port (default: 8765)")
    parser.add_argument(
        "--token",
        default=os.getenv("SPORE_HOST_METRICS_TOKEN", ""),
        help="Optional bearer token (or set SPORE_HOST_METRICS_TOKEN)",
    )
    args = parser.parse_args()

    MetricsHandler.token = args.token
    server = ThreadingHTTPServer((args.host, args.port), MetricsHandler)
    print(f"Spore host metrics bridge listening on http://{args.host}:{args.port}/metrics")
    if args.token:
        print("Authorization: Bearer <token> required")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()

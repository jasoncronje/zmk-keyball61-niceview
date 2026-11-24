#!/usr/bin/env python3
"""Serve the aim test and keep every run on disk.

    portless aimtest python3 tools/aimtest/serve.py   # -> https://aimtest.localhost
    python3 tools/aimtest/serve.py                    # plain, http://127.0.0.1:8765

Browsers refuse localStorage on file:// pages (Ardia does), so the page saves
runs here instead: one JSON file per run in tools/aimtest/runs/, which agents
can read directly.

    GET  /runs        all runs, oldest first
    POST /runs        save one run (the page does this when a run finishes)
"""
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS = os.path.join(HERE, "runs")
MAX_BODY = 20 * 1024 * 1024


def load_runs():
    if not os.path.isdir(RUNS):
        return []
    out = []
    for name in sorted(os.listdir(RUNS)):
        if name.endswith(".json"):
            try:
                with open(os.path.join(RUNS, name)) as f:
                    run = json.load(f)
                run["file"] = name
                out.append(run)
            except (OSError, ValueError):
                pass
    return out


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if path == "/runs":
            return self._send(200, json.dumps(load_runs()))
        self._send(404, '{"error":"not found"}')

    def do_POST(self):
        if self.path.split("?")[0] != "/runs":
            return self._send(404, '{"error":"not found"}')
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > MAX_BODY:
            return self._send(400, '{"error":"bad size"}')
        try:
            run = json.loads(self.rfile.read(n))
        except ValueError:
            return self._send(400, '{"error":"bad json"}')
        os.makedirs(RUNS, exist_ok=True)
        slug = re.sub(r"[^A-Za-z0-9.]+", "-", str(run.get("label", "run")))[:40].strip("-") or "run"
        name = time.strftime("%Y%m%d-%H%M%S") + "-" + slug + ".json"
        with open(os.path.join(RUNS, name), "w") as f:
            json.dump(run, f)
        self._send(200, json.dumps({"file": name}))

    def log_message(self, fmt, *args):
        if "POST" in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main():
    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("HOST", "127.0.0.1")
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"aimtest on http://{host}:{port}  (runs saved to {RUNS})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()

"""Local web server: static UI + a small REST API + a Server-Sent Events stream
for live state. Standard library only — no Flask, no websockets. Runs entirely
offline; the browser only ever talks to this process.
"""

from __future__ import annotations

import json
import mimetypes
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from engine.nodes import NODE_SPECS

# The patch panel is a React + TypeScript app (ui/src) built by Vite. The build
# output is committed, so serving it needs no Node toolchain at run time — see
# ui/README.md. Rebuild with `cd ui && npm run build` after changing the UI.
UI_DIST = Path(__file__).parent / "ui" / "dist"


class Handler(BaseHTTPRequestHandler):
    engine = None                      # injected by serve()
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):         # keep the console quiet
        pass

    # ---- helpers -------------------------------------------------
    def _send(self, code, body=b"", ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj), "application/json")

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    # ---- routing -----------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p == "/events":
            return self._events()
        if not p.startswith("/api/"):
            return self._static(p)
        if p == "/api/state":
            e = self.engine
            return self._json({
                "preset": e.current_preset,
                "presets": e.list_presets(),
                "panic": e.panic,
                "rate": e.rate,
                "modules": e.modules(),
                "nodes": NODE_SPECS,
            })
        if p == "/api/graph":
            return self._json(self.engine.graph_dict())
        if p == "/api/nodes":
            return self._json(NODE_SPECS)
        if p == "/api/presets":
            return self._json({"presets": self.engine.list_presets(),
                               "current": self.engine.current_preset})
        return self._send(404, b'{"error":"not found"}')

    def do_PUT(self):
        e, p, b = self.engine, self.path, self._body()
        if p == "/api/graph":
            try:
                e.replace_graph(b, name=b.get("name") or e.current_preset)
                return self._json({"ok": True, "graph": e.graph_dict()})
            except Exception as ex:
                return self._json({"error": str(ex)}, 400)
        if p == "/api/connection":
            c = e.update_connection(b.get("id"), chain=b.get("chain"), enabled=b.get("enabled"))
            return self._json(c or {"error": "no such connection"}, 200 if c else 404)
        return self._send(404, b'{"error":"not found"}')

    def do_POST(self):
        e, p, b = self.engine, self.path, self._body()
        if p == "/api/connect":
            if not b.get("source") or not b.get("sink"):
                return self._json({"error": "need source and sink"}, 400)
            return self._json(e.add_connection(b["source"], b["sink"], b.get("chain")))
        if p == "/api/disconnect":
            return self._json({"ok": e.remove_connection(b.get("id"))})
        if p == "/api/panic":
            e.set_panic(bool(b.get("on", True)))
            return self._json({"panic": e.panic})
        if p == "/api/preset/load":
            try:
                return self._json({"ok": True, "graph": e.load_preset(b["name"])})
            except Exception as ex:
                return self._json({"error": str(ex)}, 400)
        if p == "/api/preset/save":
            try:
                d = e.save_preset(b["name"], b.get("graph"))
                return self._json({"ok": True, "preset": d.get("name"),
                                   "presets": e.list_presets()})
            except Exception as ex:
                return self._json({"error": str(ex)}, 400)
        if p == "/api/preset/delete":
            return self._json({"ok": e.delete_preset(b.get("name")),
                               "presets": e.list_presets()})
        return self._send(404, b'{"error":"not found"}')

    # ---- static + SSE ----------------------------------------
    def _static(self, path):
        """Serve a file out of ui/dist. Vite fingerprints the asset names, so
        the set of files isn't known ahead of time — resolve the request under
        dist and refuse anything that escapes it."""
        if not UI_DIST.is_dir():
            return self._send(503, b"ui/dist is missing - run: cd ui && npm install && "
                                   b"npm run build", "text/plain")
        rel = path.lstrip("/") or "index.html"
        root = UI_DIST.resolve()
        f = (root / rel).resolve()
        if not f.is_relative_to(root) or not f.is_file():
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(str(f))[0] or "text/plain"
        self._send(200, f.read_bytes(), ctype)

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                snap = self.engine.snapshot()
                self.wfile.write(b"data: " + json.dumps(snap).encode() + b"\n\n")
                self.wfile.flush()
                time.sleep(1 / 30)
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


class Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        # A client (almost always the browser: a reload, a closed tab, an
        # idle HTTP/1.1 keep-alive socket) tearing down the connection
        # mid-request lands here as ConnectionResetError/BrokenPipeError, and
        # it happens inside socketserver's own request dispatch — before our
        # routing runs, so the try/except around the SSE stream below can't
        # catch it. It's normal keep-alive churn, not a bug; don't spam
        # stderr with a traceback for it. Anything else still prints, same
        # as the base class, since that *would* be worth seeing.
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


def serve(engine, host="127.0.0.1", port=8420):
    Handler.engine = engine
    httpd = Server((host, port), Handler)
    httpd.daemon_threads = True
    return httpd

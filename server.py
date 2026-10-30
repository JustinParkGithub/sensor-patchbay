"""Local web server: static UI + a small REST API + a Server-Sent Events stream
for live state. Standard library only — no Flask, no websockets. Runs entirely
offline; the browser only ever talks to this process.

Uploading a module and syncing runs its code, so requests are checked before
routing: the Host must be an IP, ``localhost`` or a ``.local`` name (so a web
page can't reach this server by DNS rebinding), and a POST/PUT carrying an
Origin must come from this server's own origin or a loopback one (so a page
on another site can't post to it from the browser).
"""

from __future__ import annotations

import ipaddress
import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from engine import library, paths
from engine.nodes import NODE_SPECS
from engine.registry import SINKS, SOURCES, catalog

# The patch panel is a framework-free TypeScript app (ui/src) bundled by Vite. The build
# output is committed, so serving it needs no Node toolchain at run time — see
# ui/README.md. Rebuild with `cd ui && npm run build` after changing the UI.
UI_DIST = paths.APP / "ui" / "dist"
LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def _hostname(value: str) -> str | None:
    try:
        return urlsplit(value if "//" in value else f"//{value}").hostname
    except ValueError:
        return None


def _local_name(host: str) -> bool:
    if host in LOOPBACK or host.endswith((".localhost", ".local")):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


class Handler(BaseHTTPRequestHandler):
    engine = None                      # injected by serve()
    on_quit = None                     # injected by serve(): stops the whole process
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

    def _allowed(self) -> bool:
        """See the module docstring. A request with no Host/Origin (curl, a
        script) is let through: only browsers are tricked into sending these."""
        host = _hostname(self.headers.get("Host", ""))
        if host is not None and not _local_name(host):
            return False
        if self.command in ("POST", "PUT"):
            origin = self.headers.get("Origin")
            if origin is not None:
                o = _hostname(origin)
                if o is None or (o != host and o not in LOOPBACK):
                    return False
        return True

    def _refuse(self):
        self.close_connection = True
        self._json({"error": "request refused (cross-origin or unknown host)"}, 403)

    # ---- routing -----------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._allowed():
            return self._refuse()
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
                "preset_info": e.preset_info(),
                "panic": e.panic,
                "rate": e.rate,
                "modules": e.modules(),
                "nodes": NODE_SPECS,
                "plugins": self._plugins(),
            })
        if p.startswith("/api/source/") and p.endswith("/preview"):
            return self._preview(p[len("/api/source/"):-len("/preview")])
        if p == "/api/plugins":
            return self._json(self._plugins())
        if p == "/api/graph":
            return self._json(self.engine.graph_dict())
        if p == "/api/nodes":
            return self._json(NODE_SPECS)
        if p == "/api/presets":
            return self._json({"presets": self.engine.list_presets(),
                               "current": self.engine.current_preset})
        return self._send(404, b'{"error":"not found"}')

    def do_PUT(self):
        if not self._allowed():
            return self._refuse()
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
        if not self._allowed():
            return self._refuse()
        if self.path.split("?", 1)[0] == "/api/upload":
            return self._upload()
        e, p, b = self.engine, self.path, self._body()
        if p == "/api/quit":
            if self.on_quit is None:
                return self._json({"error": "quitting isn't available here"}, 501)
            self.close_connection = True
            self._json({"ok": True})
            # After the reply is out: quitting stops this server.
            threading.Timer(0.2, type(self).on_quit).start()
            return
        if p == "/api/connect":
            if not b.get("source") or not b.get("sink"):
                return self._json({"error": "need source and sink"}, 400)
            return self._json(e.add_connection(b["source"], b["sink"], b.get("chain")))
        if p == "/api/disconnect":
            return self._json({"ok": e.remove_connection(b.get("id"))})
        if p == "/api/source":
            return self._add_module("source", b)
        if p == "/api/sink":
            return self._add_module("sink", b)
        if p == "/api/source/remove":
            return self._remove_module("source", b)
        if p == "/api/sink/remove":
            return self._remove_module("sink", b)
        if p == "/api/panic":
            e.set_panic(bool(b.get("on", True)))
            return self._json({"panic": e.panic})
        if p == "/api/rate":
            try:
                return self._json({"ok": True, "rate": e.set_rate(b.get("rate"))})
            except Exception as ex:
                return self._json({"error": str(ex)}, 400)
        if p == "/api/preset/load":
            try:
                return self._json({"ok": True, "graph": e.load_preset(b["name"]),
                                   "missing": e.preset_info().get(b["name"], {}).get("missing", [])})
            except Exception as ex:
                return self._json({"error": str(ex)}, 400)
        if p == "/api/preset/save":
            try:
                d = e.save_preset(b["name"], b.get("graph"))
                return self._json({"ok": True, "preset": d.get("name"),
                                   "presets": e.list_presets(),
                                   "preset_info": e.preset_info()})
            except Exception as ex:
                return self._json({"error": str(ex)}, 400)
        if p == "/api/preset/delete":
            try:
                ok = e.delete_preset(b.get("name"))
            except Exception as ex:
                return self._json({"error": str(ex)}, 400)
            return self._json({"ok": ok, "presets": e.list_presets(),
                               "preset_info": e.preset_info()})
        if p == "/api/sync":
            try:
                report = library.sync(upgrade=bool(b.get("upgrade")))
            except Exception as ex:
                return self._json({"error": f"sync failed: {ex}"}, 500)
            return self._json({"ok": True, "report": report, "plugins": self._plugins(),
                               "presets": e.list_presets(), "preset_info": e.preset_info()})
        return self._send(404, b'{"error":"not found"}')

    # ---- uploads ---------------------------------------------
    def _upload(self):
        """``POST /api/upload?filename=x.zip`` with the file as the raw body.
        Installs it (see engine/library.py); the client syncs afterwards."""
        q = parse_qs(urlsplit(self.path).query)
        filename = Path((q.get("filename") or [""])[0]).name
        n = int(self.headers.get("Content-Length", 0) or 0)
        if not filename or not n:
            return self._json({"error": "need ?filename= and a file body"}, 400)
        if n > library.MAX_UPLOAD:
            self.close_connection = True   # don't read it all just to refuse it
            return self._json({"error": f"{filename}: larger than "
                                        f"{library.MAX_UPLOAD >> 20} MB"}, 413)
        try:
            result = library.install_upload(filename, self.rfile.read(n))
        except ValueError as ex:
            return self._json({"error": str(ex)}, 400)
        return self._json({"ok": True, **result})

    # ---- plugins / modules -----------------------------------
    @staticmethod
    def _plugins():
        return {"sources": catalog(SOURCES, "source"),
                "sinks": catalog(SINKS, "sink")}

    def _add_module(self, kind, b):
        type_name = b.get("type")
        if not type_name:
            return self._json({"error": "need a plugin type"}, 400)
        create = self.engine.create_source if kind == "source" else self.engine.create_sink
        try:
            iid = create(type_name, b.get("args") or {}, b.get("id") or None)
        except Exception as ex:
            return self._json({"error": f"{type_name}: {ex}"}, 400)
        return self._json({"ok": True, "id": iid, "modules": self.engine.modules()})

    def _remove_module(self, kind, b):
        iid = b.get("id")
        remove = self.engine.remove_source if kind == "source" else self.engine.remove_sink
        try:
            dropped = remove(iid)
        except Exception as ex:
            return self._json({"error": str(ex)}, 400)
        return self._json({"ok": True, "dropped": dropped,
                           "modules": self.engine.modules(),
                           "graph": self.engine.graph_dict()})

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


    def _preview(self, iid):
        """MJPEG stream of a source's preview frames (an <img> plays it as video).
        Ends when the source is removed; the browser's <img> just goes blank."""
        src = self.engine.sources.get(iid)
        if src is None or not getattr(src, "PREVIEW", False):
            return self._send(404, b'{"error":"no preview"}')
        self.close_connection = True       # no Content-Length: the stream ends the connection
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        last = None
        try:
            while self.engine.sources.get(iid) is src:
                jpeg = src.preview_jpeg()
                if jpeg is not None and jpeg is not last:
                    last = jpeg
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                     b"Content-Length: " + str(len(jpeg)).encode() +
                                     b"\r\n\r\n" + jpeg + b"\r\n")
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


def serve(engine, host="127.0.0.1", port=8420, on_quit=None):
    """*on_quit* is what the UI's Quit calls (on a worker thread); without one,
    ``POST /api/quit`` is refused."""
    Handler.engine = engine
    Handler.on_quit = staticmethod(on_quit) if on_quit else None
    httpd = Server((host, port), Handler)
    httpd.daemon_threads = True
    return httpd

"""HTTP requests on a button press: home automation, a local script's server, a
hosted automation service. Standard library only.

Port semantics
--------------
  hook.1 .. hook.4   a rising edge requests that hook's URL (``url1`` .. ``url4``).
                     POST sends ``{"port": "hook.1", "value": 1.0}`` as JSON.

URLs are set on the sink, never in a preset, so loading someone's preset can't
send requests anywhere you didn't choose. Requests run on a worker thread so a
slow server never stalls the engine; a panic drops any still queued.
"""

from __future__ import annotations

import json
import queue
import threading
import urllib.request
from urllib.parse import urlsplit

from engine.registry import register_sink
from engine.signals import PortSpec, EVENT
from sinks.base import Sink

_HOOKS = 4
_TIMEOUT_S = 3.0


@register_sink
class WebhookSink(Sink):
    type = "webhook"
    id = "webhook"
    label = "webhooks (HTTP)"
    PORTS = [PortSpec(f"hook.{i}", EVENT, f"hook.{i}", "hooks") for i in range(1, _HOOKS + 1)]
    ARGS = {
        **{f"url{i}": {"default": "", "type": str, "help": f"http(s) URL for hook.{i}"}
           for i in range(1, _HOOKS + 1)},
        "method": {"default": "POST", "type": str, "help": "POST or GET"},
    }

    def __init__(self, url1="", url2="", url3="", url4="", method="POST"):
        self.method = str(method or "POST").upper()
        if self.method not in ("GET", "POST"):
            raise ValueError(f"method must be GET or POST, not {method!r}")
        self.urls = {}
        for i, url in enumerate((url1, url2, url3, url4), start=1):
            if not url:
                continue
            if urlsplit(url).scheme not in ("http", "https"):
                raise ValueError(f"url{i} must be http(s), got {url!r}")
            self.urls[f"hook.{i}"] = url
        self._prev: dict[str, float] = {}
        self._queue: queue.Queue = queue.Queue(maxsize=16)
        self._thread = None
        self._err = None

    def start(self):
        self._thread = threading.Thread(target=self._work, name="webhook", daemon=True)
        self._thread.start()

    def stop(self):
        self.release_all()
        if self._thread:
            self._queue.put(None)
            self._thread.join(timeout=_TIMEOUT_S + 1)
            self._thread = None

    def status(self):
        return f"error: {self._err}" if self._err else "ok"

    def apply(self, values, dt):
        for port, url in self.urls.items():
            value = values.get(port, 0.0)
            if value >= 0.5 and self._prev.get(port, 0.0) < 0.5:
                try:
                    self._queue.put_nowait((port, url))
                except queue.Full:
                    self._err = "too many requests queued; dropped one"
            self._prev[port] = value

    def _work(self):
        while (job := self._queue.get()) is not None:
            port, url = job
            body = json.dumps({"port": port, "value": 1.0}).encode() if self.method == "POST" else None
            req = urllib.request.Request(url, data=body, method=self.method,
                                         headers={"Content-Type": "application/json"} if body else {})
            try:
                with urllib.request.urlopen(req, timeout=_TIMEOUT_S):
                    pass
                self._err = None
            except Exception as e:
                self._err = f"{port}: {e}"

    def release_all(self):
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass

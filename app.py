#!/usr/bin/env python3
"""sensor-patchbay desktop app: the patch panel in a native window, plus a tray
icon that keeps the engine running when the window is closed.

This is what the packaged executable runs. It is ``run.py``'s startup (same
flags, same engine, same server), with the browser tab replaced by a window:

    python app.py                 # native window + tray icon
    python app.py --browser       # tray icon, patch panel in the default browser
    python app.py --no-tray       # window only; closing it quits

Closing the window hides it; the engine keeps driving outputs until you quit:
*Quit* in the patch panel's top bar or the tray menu, or Cmd+Q / the app menu
on macOS. Without a tray (``--no-tray``, or no tray support on this desktop)
closing the window quits too.

Any of run.py's console / one-shot flags (``--cli``, ``--no-ui``, ``--sync``,
``--list-sources``, ...) skip the window and behave exactly like run.py, so the
packaged ``patchbay`` executable is also the command-line tool:

    patchbay --cli                # web UI + interactive console, no window
    patchbay --no-ui --cli        # console only (headless)

If the patch panel is already running on the port, this opens it and exits
instead of starting a second engine.

Needs ``pywebview`` for the window and ``pystray`` + ``Pillow`` for the tray
(``packaging/requirements.txt``); either one missing just falls back (browser
tab / no tray) rather than failing.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

import run
from engine import paths

TITLE = "sensor · patchbay"
# run.py flags that mean "no window": they either exit or own the terminal.
CONSOLE_FLAGS = ("cli", "no_ui", "sync", "upgrade", "list_sources", "list_sinks",
                 "selftest", "catalog")
APP_FLAGS = ("--browser", "--no-tray")


def build_parser():
    ap = run.build_parser()
    ap.description = __doc__
    ap.add_argument("--browser", action="store_true",
                    help="open the patch panel in the default browser, not a window")
    ap.add_argument("--no-tray", action="store_true",
                    help="no tray icon; closing the window quits")
    return ap


def _running_instance(host: str, port: int) -> str | None:
    """The URL of a patch panel already serving on host:port, if there is one."""
    url = f"http://{host}:{port}"
    try:
        with urllib.request.urlopen(f"{url}/api/presets", timeout=0.5) as res:
            if "presets" in json.load(res):
                return url
    except Exception:
        pass
    return None


def _reveal(folder):
    """Open *folder* in the platform's file manager."""
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(folder)  # noqa: S606 - a folder, not a program
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])


def _tray_image():
    """The tray icon, drawn here so the app ships no image files: an amber jack
    and a teal jack joined by a violet cable, on the UI's dark panel colour."""
    from PIL import Image, ImageDraw

    n = 64
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, n - 3, n - 3), radius=14, fill=(28, 32, 36, 255))
    d.line([(18, 40), (26, 22), (38, 22), (46, 40)], fill=(168, 147, 224, 255), width=5, joint="curve")
    d.ellipse((9, 34, 27, 52), fill=(224, 161, 92, 255))
    d.ellipse((37, 34, 55, 52), fill=(95, 184, 184, 255))
    return img


def _has_display() -> bool:
    """False on a Linux box with no graphical session. GTK, which both pywebview
    and pystray use there, exits the whole process if it can't open a display."""
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _app_terminating() -> bool:
    """macOS: True while the app is being asked to quit (Cmd+Q, the app or Dock
    menu's Quit, logging out) rather than to close the window. pywebview sends
    both through the window's closing event, synchronously; a quit arrives via
    the app delegate's ``applicationShouldTerminate_``, which is then on the stack."""
    frame = sys._getframe(1)
    while frame is not None:
        if frame.f_code.co_name == "applicationShouldTerminate_":
            return True
        frame = frame.f_back
    return False


def _on_main_thread(fn):
    """Run *fn* on the main thread when a Cocoa app owns it (the window, or the
    tray's run loop on macOS), else right away."""
    if sys.platform == "darwin" and threading.current_thread() is not threading.main_thread():
        from AppKit import NSApp
        if NSApp() is not None:
            from PyObjCTools import AppHelper
            return AppHelper.callAfter(fn)
    fn()


class Api:
    """What the patch panel can call in the native window (``window.pywebview.api``).
    pywebview exposes the public methods; the window is kept private."""

    def __init__(self):
        self._window = None

    def pick_files(self):
        """Upload's file picker, opened in the data folder (modules + presets).
        Returns ``[{name, data}]`` with base64 contents, or None if cancelled; the
        page then uploads them as if they'd come from its own file input."""
        import webview

        picked = self._window.create_file_dialog(
            webview.FileDialog.OPEN, directory=str(paths.DATA), allow_multiple=True,
            file_types=("Modules and presets (*.zip;*.json)",))
        if not picked:
            return None
        return [{"name": Path(p).name, "data": base64.b64encode(Path(p).read_bytes()).decode("ascii")}
                for p in picked]


class Desktop:
    """The window and the tray icon around one running engine."""

    def __init__(self, engine, url: str, browser: bool, tray: bool):
        self.engine = engine
        self.url = url
        self.use_window = not browser
        self.use_tray = tray
        self.window = None
        self.icon = None
        self.quitting = threading.Event()

    # ---- tray ------------------------------------------------------
    def _make_tray(self):
        try:
            import pystray
            image = _tray_image()
        except Exception as e:   # not installed, or no tray backend on this desktop
            print(f"[app] no tray icon ({type(e).__name__}: {e})")
            return None
        item, sep = pystray.MenuItem, pystray.Menu.SEPARATOR
        menu = pystray.Menu(
            item("Open patch panel", lambda: self.show(), default=True),
            item("Open in browser", lambda: webbrowser.open(self.url)),
            sep,
            item("Panic (all outputs off)", lambda: self.engine.set_panic(not self.engine.panic),
                 checked=lambda _: self.engine.panic),
            item("Open data folder", lambda: _reveal(paths.DATA)),
            sep,
            item("Quit", lambda: self.quit()),
        )
        return pystray.Icon("sensor-patchbay", image, TITLE, menu)

    # ---- actions ---------------------------------------------------
    def show(self):
        if self.window is not None:
            self.window.show()
            self.window.restore()
        else:
            webbrowser.open(self.url)

    def quit(self):
        """Close everything; run() then returns and main() stops the engine.
        Safe from any thread (the tray menu, the UI's Quit request, Cmd+Q)."""
        self.quitting.set()

        def close():
            if self.icon is not None:
                self.icon.stop()
            if self.window is not None:
                self.window.destroy()
        _on_main_thread(close)

    def _on_closing(self):
        """Closing the window only hides it while the tray can bring it back.
        Quitting the app (macOS) quits: through quit() rather than letting Cocoa
        terminate, which would exit() before main() releases held keys."""
        if self.quitting.is_set():
            return True
        if _app_terminating():
            self.quit()
            return False        # cancel Cocoa's terminate; quit() shuts down cleanly
        if self.icon is not None:
            self.window.hide()
            return False        # cancel the close
        return True

    # ---- main loop -------------------------------------------------
    def _wait(self):
        while not self.quitting.wait(0.5):   # a timeout keeps Ctrl+C working on Windows
            pass

    def run(self):
        webview = None
        if not _has_display():
            print("[app] no display; serving the patch panel only (try --cli for a console)")
            self.use_window = self.use_tray = False
        if self.use_window:
            try:
                import webview
            except Exception as e:
                print(f"[app] no native window ({type(e).__name__}: {e}); using the browser")
        self.icon = self._make_tray() if self.use_tray else None

        if webview is None:
            webbrowser.open(self.url)
            print(f"  patch panel  ->  {self.url}")
            if self.icon is not None:
                self.icon.run()        # until Quit
            else:
                print("  Ctrl+C to stop\n")
                self._wait()
            return

        api = Api()
        self.window = webview.create_window(TITLE, self.url, width=1280, height=820,
                                            min_size=(900, 600), background_color="#14171a",
                                            js_api=api)
        api._window = self.window
        self.window.events.closing += self._on_closing
        if self.icon is not None:
            # The GUI toolkit owns the main loop; the icon hooks into it
            # (macOS, GTK) or runs its own thread (Windows, X11).
            self.icon.run_detached()
        try:
            webview.start()
        except Exception as e:     # e.g. no GUI backend for pywebview on this Linux
            print(f"[app] native window failed ({type(e).__name__}: {e}); using the browser")
            self.window = None
            webbrowser.open(self.url)
            if self.icon is None:
                print("  Ctrl+C to stop\n")
            self._wait()
        if self.icon is not None:
            self.icon.stop()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    args = build_parser().parse_args(argv)
    if any(getattr(args, flag) for flag in CONSOLE_FLAGS):
        return run.main([a for a in argv if a not in APP_FLAGS])

    existing = _running_instance(args.host, args.port)
    if existing:
        print(f"[app] already running at {existing}; opening it")
        webbrowser.open(existing)
        return

    if run.prepare(args):
        return
    engine = run.start_engine(args)
    desktop = Desktop(engine, "", browser=args.browser, tray=not args.no_tray)
    from server import serve
    try:
        httpd = serve(engine, args.host, args.port, on_quit=desktop.quit)
    except OSError as e:          # the port is taken by something else: pick a free one
        print(f"[app] port {args.port} unavailable ({e}); using a free port")
        httpd = serve(engine, args.host, 0, on_quit=desktop.quit)
    desktop.url = url = f"http://{args.host}:{httpd.server_address[1]}"
    threading.Thread(target=httpd.serve_forever, name="httpd", daemon=True).start()
    print(f"[app] data folder: {paths.DATA}")

    try:
        desktop.run()
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        engine.stop()             # releases any held keys/buttons
        httpd.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    sys.exit(main())

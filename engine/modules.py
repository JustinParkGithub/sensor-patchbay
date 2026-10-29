"""Declarative modules — what's installed follows from what's on disk.

Inspired by NixOS: every source/sink *declares* what it needs, the set of module
folders (minus anything ``patchbay.toml`` disables) *is* the configuration, and
one sync makes the Python environment match it exactly — missing packages are
installed and anything no enabled module needs is removed.

Module folders
--------------
A module is a package folder named after its registry type, holding the plugin
code (``__init__.py``) and a ``module.toml`` manifest::

    sources/bmi160/
      __init__.py
      module.toml
      firmware/...

    # module.toml
    kind    = "source"                  # optional in-repo (the parent folder decides)
    python  = ["pyserial>=3.5"]         # pip requirement strings (PEP 508 markers ok)
    depends = []                        # other modules whose *code* this one imports
    system  = ["Linux: user in 'dialout'"]   # things pip can't manage; printed on sync
    [[assets]]                          # files fetched into the module folder
    file   = "model.task"
    url    = "https://..."
    sha256 = "..."

The manifest is read without importing the module, so an extension's
dependencies can be resolved without running its code.

Sync
----
:func:`ensure` (run on every start, skipped by ``--no-sync``):

1. find every module folder, drop the disabled ones and any whose ``depends``
   are missing;
2. if the union of their ``python`` lists changed since ``patchbay.lock`` was
   written (or ``upgrade`` is set), re-resolve it with ``uv pip compile
   --universal`` — one lock, valid on every platform;
3. ``uv pip sync patchbay.lock`` into the running interpreter's environment —
   exact, so leftovers are uninstalled. A no-op sync needs no network;
4. fetch missing/changed ``assets`` and check their sha256.

It all runs before :func:`engine.registry.discover`, which then imports only the
enabled modules.

Packaged app
------------
A frozen app can't install into its own interpreter, so step 3 differs there:
the lock is installed with ``uv pip install --target`` into a fresh
``site-packages/<lock digest>/`` folder in the data folder (see
:mod:`engine.paths`), which then goes on ``sys.path``. A changed lock gets a new
folder rather than an in-place edit, so packages a running module has loaded
are never pulled out from under it; stale folders are deleted on the next start.
With nothing to install, uv isn't run at all.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import paths

CONFIG = paths.CONFIG
LOCK = paths.LOCK
KINDS = paths.KINDS
MIN_PYTHON = "3.11"          # tomllib; the lock is resolved for this and newer

_DIGEST_PREFIX = "# patchbay-inputs: "
_MANIFEST_KEYS = {"kind", "python", "depends", "system", "assets"}


@dataclass
class Module:
    name: str                      # folder name == registry type
    kind: str                      # "source" | "sink"
    path: Path
    python: list[str] = field(default_factory=list)
    depends: list[str] = field(default_factory=list)
    system: list[str] = field(default_factory=list)
    assets: list[dict] = field(default_factory=list)
    external: bool = False         # loaded from an --ext / PATCHBAY_EXT_PATH dir


_captured: list[list[str]] = []


def _say(line: str):
    """Print a sync message, and keep it for whoever is :func:`capture`-ing."""
    print(line)
    for log in _captured:
        log.append(line)


def _warn(msg: str):
    _say(f"[modules] {msg}")


@contextlib.contextmanager
def capture():
    """Collect every message printed while the block runs (the UI's sync report)."""
    log: list[str] = []
    _captured.append(log)
    try:
        yield log
    finally:
        _captured.remove(log)


def _shown(path: Path) -> Path:
    for root in (paths.APP, paths.DATA):
        if path.is_relative_to(root):
            return path.relative_to(root)
    return path


# ----------------------------------------------------------------------- finding
def _read_module(folder: Path, kind: str | None, external: bool) -> Module | None:
    manifest = folder / "module.toml"
    if not (folder / "__init__.py").is_file():
        return None
    if not manifest.is_file():
        _warn(f"{_shown(folder)}: no module.toml, skipped")
        return None
    try:
        data = tomllib.loads(manifest.read_text())
    except tomllib.TOMLDecodeError as e:
        _warn(f"{manifest}: {e}; skipped")
        return None
    for key in sorted(set(data) - _MANIFEST_KEYS):
        _warn(f"{manifest}: unknown key {key!r} ignored")
    declared = data.get("kind")
    if kind and declared and declared != kind:
        _warn(f"{manifest}: kind {declared!r} doesn't match its folder ({kind}); using {kind}")
    kind = kind or declared
    if kind not in KINDS.values():
        _warn(f"{manifest}: needs kind = \"source\" or \"sink\"; skipped")
        return None
    return Module(folder.name, kind, folder,
                  python=list(data.get("python", [])),
                  depends=list(data.get("depends", [])),
                  system=list(data.get("system", [])),
                  assets=list(data.get("assets", [])),
                  external=external)


def find_modules(extra_dirs: list | None = None) -> list[Module]:
    """Every module folder under ``sources/``, ``sinks/`` (the repo's, and the data
    folder's — see :mod:`engine.paths`) and the extension dirs."""
    from engine.registry import extension_dirs  # avoid a cycle at import time

    found: dict[str, Module] = {}
    candidates = [(parent, kind, False) for parent, kind in paths.module_dirs()]
    candidates += [(Path(d).expanduser(), None, True)
                   for d in extension_dirs() + list(extra_dirs or [])]
    for parent, kind, external in candidates:
        if not parent.is_dir():
            continue
        for folder in sorted(p for p in parent.iterdir() if p.is_dir()):
            if folder.name.startswith(("_", ".")):
                continue
            mod = _read_module(folder, kind, external)
            if mod is None:
                continue
            if mod.name in found:
                _warn(f"{folder}: a module named {mod.name!r} already exists "
                      f"({found[mod.name].path}); skipped")
                continue
            found[mod.name] = mod
    return list(found.values())


def load_config() -> dict:
    """``patchbay.toml`` (all keys optional): ``python``, ``disable``, ``autostart``."""
    if not CONFIG.is_file():
        return {}
    return tomllib.loads(CONFIG.read_text())


def resolve(modules: list[Module], config: dict) -> list[Module]:
    """Drop disabled modules, then (repeatedly) any whose ``depends`` are gone."""
    by_name = {m.name: m for m in modules}
    disabled = set(config.get("disable", []))
    for name in sorted(disabled - set(by_name)):
        _warn(f"patchbay.toml disables {name!r}, but no such module exists")
    enabled = {n: m for n, m in by_name.items() if n not in disabled}
    changed = True
    while changed:
        changed = False
        for name, mod in list(enabled.items()):
            missing = [d for d in mod.depends if d not in enabled]
            if missing:
                _warn(f"{name} disabled: depends on {', '.join(missing)}")
                del enabled[name]
                changed = True
    return list(enabled.values())


# -------------------------------------------------------------------------- lock
def _inputs(enabled: list[Module], config: dict) -> dict[str, list[str]]:
    """``{"<label>.in": requirements}`` — one file per module, so the lock's
    ``# via`` annotations name the module that asked for each package."""
    files = {"core.in": list(config.get("python", []))}
    for m in sorted(enabled, key=lambda m: (m.kind, m.name)):
        if m.python:
            files[f"{m.kind}s/{m.name}.in"] = m.python
    return files


def _digest(files: dict[str, list[str]]) -> str:
    blob = "\n".join(f"{k}:{r}" for k in sorted(files) for r in sorted(files[k]))
    return hashlib.sha256(f"{MIN_PYTHON}\n{blob}".encode()).hexdigest()[:16]


def _lock_digest() -> str | None:
    if not LOCK.is_file():
        return None
    first = LOCK.read_text().splitlines()[:1]
    return first[0][len(_DIGEST_PREFIX):].strip() if first and first[0].startswith(_DIGEST_PREFIX) else None


def _find_uv() -> str | None:
    bundled = paths.APP / ("uv.exe" if sys.platform == "win32" else "uv")
    if paths.FROZEN and bundled.is_file():
        return str(bundled)
    try:
        from uv import find_uv_bin       # the `uv` package, installed by the core lock
        return find_uv_bin()
    except Exception:
        return shutil.which("uv")


def _child_env() -> dict | None:
    """The environment for uv. A frozen app on Linux points LD_LIBRARY_PATH at its
    own bundled libraries; the Python uv runs must not pick those up."""
    if not paths.FROZEN or "LD_LIBRARY_PATH_ORIG" not in os.environ:
        return None
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = env.pop("LD_LIBRARY_PATH_ORIG")
    return env


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=_child_env())


def compile_lock(uv: str, files: dict[str, list[str]], upgrade: bool = False) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        for rel, reqs in files.items():
            p = Path(tmp, rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("\n".join(reqs) + "\n")
        out = Path(tmp, "lock.txt")
        cmd = [uv, "pip", "compile", *sorted(files), "--universal",
               "--python-version", MIN_PYTHON, "--no-header", "--quiet", "-o", out.name]
        if upgrade:
            cmd.append("--upgrade")
        elif LOCK.is_file():
            shutil.copy(LOCK, out)  # uv keeps existing pins that still fit
        res = _run(cmd, cwd=Path(tmp))
        if res.returncode != 0:
            _warn("resolving dependencies failed (a conflict names the modules' "
                  "files, e.g. sources/cv.in):\n" + res.stderr.strip())
            return False
        body = out.read_text()
    LOCK.write_text(
        f"{_DIGEST_PREFIX}{_digest(files)}\n"
        "# Generated from the module.toml of every enabled module + patchbay.toml.\n"
        "# Don't edit: change a manifest and run `python run.py --sync`.\n"
        + body)
    _say("[modules] patchbay.lock updated")
    return True


def sync_env(uv: str) -> bool:
    res = _run([uv, "pip", "sync", "--python", sys.executable, str(LOCK)])
    lines = [l for l in res.stderr.splitlines() if l.strip()]
    changed = [l for l in lines if not l.lstrip().startswith(("Resolved", "Audited", "Checked"))]
    for line in (lines if res.returncode else changed):
        _say(f"  {line}")
    if res.returncode != 0:
        _warn("sync failed; continuing with the environment as it is")
        return False
    return bool(changed)


# ------------------------------------------------------- packaged app: --target
def _python_platform() -> str:
    """The running interpreter's platform, in uv's ``--python-platform`` terms."""
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "x64": "x86_64", "arm64": "aarch64"}.get(machine, machine)
    if sys.platform == "win32":
        return f"{arch}-pc-windows-msvc"
    if sys.platform == "darwin":
        return f"{arch}-apple-darwin"
    return f"{arch}-unknown-linux-gnu"


def _lock_requirements() -> list[str]:
    if not LOCK.is_file():
        return []
    return [l for l in LOCK.read_text().splitlines() if l.strip() and not l.lstrip().startswith("#")]


def _activate_site(folder: Path):
    """Put *folder* on ``sys.path`` in place of any other site-packages version."""
    root = str(paths.SITE)
    sys.path[:] = [p for p in sys.path if not p.startswith(root)]
    sys.path.append(str(folder))
    import importlib
    importlib.invalidate_caches()


_pruned = False


def _uv_install(uv: str, target: Path, reqs: list[str]) -> subprocess.CompletedProcess:
    py = f"{sys.version_info.major}.{sys.version_info.minor}"
    # A package with no wheel for this platform gets built, which needs that
    # same Python version with its headers: uv's own managed builds have them
    # (it downloads one the first time), a system Python often doesn't.
    return _run([uv, "pip", "install", "--target", str(target), "--python", py,
                 "--managed-python", "--python-version", py,
                 "--python-platform", _python_platform(), "--link-mode", "copy",
                 "--no-deps", *reqs])


def sync_target(uv: str | None) -> bool:
    """Install the lock into ``site-packages/<digest>/`` and activate it.
    Returns True if anything was installed.

    If the lock won't install in one go, each package is tried on its own, so
    one that can't be built here only costs the module that needs it. Such a
    folder is marked partial and retried on the next sync; until a new folder
    is in use, the last one that was stays on disk.
    """
    global _pruned
    digest = _lock_digest() or "empty"
    target = paths.SITE / digest
    current = paths.SITE / "current"
    paths.SITE.mkdir(parents=True, exist_ok=True)
    if not _pruned:
        # Nothing from these has been imported yet this run, so they can go.
        _pruned = True
        keep = {digest, current.read_text().strip() if current.is_file() else ""}
        for old in paths.SITE.iterdir():
            if old.is_dir() and old.name not in keep:
                shutil.rmtree(old, ignore_errors=True)
    if (target / ".complete").is_file():
        _activate_site(target)
        return False
    reqs = _lock_requirements()
    if reqs and uv is None:
        _warn("uv not found; can't install module packages")
        return False
    part = paths.SITE / f"{digest}.part"
    shutil.rmtree(part, ignore_errors=True)
    part.mkdir()
    failed = []
    if reqs:
        _say(f"[modules] installing {len(reqs)} package(s)...")
        if _uv_install(uv, part, ["-r", str(LOCK)]).returncode != 0:
            _say("[modules] some packages failed; installing one at a time")
            for req in reqs:
                res = _uv_install(uv, part, [req])
                if res.returncode != 0:
                    failed.append(req.split(";")[0].strip())
                    why = [l.strip() for l in res.stderr.splitlines() if l.strip()]
                    _say(f"  {failed[-1]}: failed ({why[-1] if why else 'no output'})")
    if failed:
        _warn(f"couldn't install {', '.join(failed)}; modules that need them stay "
              "unavailable (retried on the next sync)")
        (part / ".partial").write_text("\n".join(failed) + "\n")
    else:
        (part / ".complete").write_text("")
    shutil.rmtree(target, ignore_errors=True)
    try:
        part.rename(target)
    except OSError:      # Windows: a retried partial folder still has files in use
        _warn("packages installed, but in use; restart the app to switch to them")
        return False
    current.write_text(digest)
    _activate_site(target)
    return bool(reqs)


# ------------------------------------------------------------------------ assets
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_assets(enabled: list[Module]):
    for m in enabled:
        for asset in m.assets:
            target = m.path / asset["file"]
            want = asset.get("sha256")
            if target.is_file() and (not want or _sha256(target) == want):
                continue
            if target.is_file():
                _warn(f"{m.name}/{asset['file']}: hash mismatch, re-downloading")
            _say(f"[modules] {m.name}: fetching {asset['file']}")
            part = target.with_name(target.name + ".part")
            try:
                urllib.request.urlretrieve(asset["url"], part)
                if want and _sha256(part) != want:
                    raise ValueError(f"sha256 mismatch (expected {want})")
                part.replace(target)
            except Exception as e:
                part.unlink(missing_ok=True)
                _warn(f"{m.name}/{asset['file']}: {e}")


# ------------------------------------------------------------------------ driver
def ensure(extra_dirs: list | None = None, sync: bool = True,
           upgrade: bool = False, verbose: bool = False) -> list[Module]:
    """Find + resolve modules and (unless ``sync`` is false) make the environment
    match them. Returns the enabled modules, for :func:`engine.registry.discover`."""
    config = load_config()
    enabled = resolve(find_modules(extra_dirs), config)
    if not sync:
        if paths.FROZEN:   # use what's installed, as it is
            current = paths.SITE / "current"
            for name in (_lock_digest() or "empty",
                         current.read_text().strip() if current.is_file() else ""):
                if name and (paths.SITE / name).is_dir():
                    _activate_site(paths.SITE / name)
                    break
        return enabled
    files = _inputs(enabled, config)
    uv = _find_uv()
    if paths.FROZEN and not any(files.values()):
        # Nothing to install: don't need uv, the network, or a Python for it.
        if _lock_digest() != _digest(files):
            LOCK.write_text(f"{_DIGEST_PREFIX}{_digest(files)}\n")
        changed = sync_target(None)
    elif uv is None:
        _warn("uv not found (pip install uv); skipping the environment sync")
        return enabled
    else:
        if upgrade or _lock_digest() != _digest(files):
            _say("[modules] module requirements changed; resolving...")
            if not compile_lock(uv, files, upgrade):
                return enabled
        changed = sync_target(uv) if paths.FROZEN else sync_env(uv)
    fetch_assets(enabled)
    if changed or verbose:
        notes = [(m.name, n) for m in enabled for n in m.system]
        if notes:
            _say("[modules] system setup pip can't do for you:")
            for name, note in notes:
                _say(f"  {name:8} {note}")
    return enabled


def system_notes(enabled: list[Module]) -> list[dict]:
    return [{"module": m.name, "note": n} for m in enabled for n in m.system]

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
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "patchbay.toml"
LOCK = ROOT / "patchbay.lock"
KINDS = {"sources": "source", "sinks": "sink"}
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


def _warn(msg: str):
    print(f"[modules] {msg}")


# ----------------------------------------------------------------------- finding
def _read_module(folder: Path, kind: str | None, external: bool) -> Module | None:
    manifest = folder / "module.toml"
    if not (folder / "__init__.py").is_file():
        return None
    if not manifest.is_file():
        _warn(f"{folder.relative_to(ROOT) if not external else folder}: no module.toml, skipped")
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
    """Every module folder under ``sources/``, ``sinks/`` and the extension dirs."""
    from engine.registry import extension_dirs  # avoid a cycle at import time

    found: dict[str, Module] = {}
    candidates = [(ROOT / parent, kind, False) for parent, kind in KINDS.items()]
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
    try:
        from uv import find_uv_bin       # the `uv` package, installed by the core lock
        return find_uv_bin()
    except Exception:
        return shutil.which("uv")


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


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
    print("[modules] patchbay.lock updated")
    return True


def sync_env(uv: str) -> bool:
    res = _run([uv, "pip", "sync", "--python", sys.executable, str(LOCK)])
    lines = [l for l in res.stderr.splitlines() if l.strip()]
    changed = [l for l in lines if not l.lstrip().startswith(("Resolved", "Audited", "Checked"))]
    for line in (lines if res.returncode else changed):
        print(f"  {line}")
    if res.returncode != 0:
        _warn("sync failed; continuing with the environment as it is")
        return False
    return bool(changed)


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
            print(f"[modules] {m.name}: fetching {asset['file']}")
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
        return enabled
    uv = _find_uv()
    if uv is None:
        _warn("uv not found (pip install uv); skipping the environment sync")
        return enabled
    files = _inputs(enabled, config)
    if upgrade or _lock_digest() != _digest(files):
        print("[modules] module requirements changed; resolving...")
        if not compile_lock(uv, files, upgrade):
            return enabled
    changed = sync_env(uv)
    fetch_assets(enabled)
    if changed or verbose:
        notes = [(m.name, n) for m in enabled for n in m.system]
        if notes:
            print("[modules] system setup pip can't do for you:")
            for name, note in notes:
                print(f"  {name:8} {note}")
    return enabled

"""Adding modules and presets from the UI, and re-reading what's installed.

Two front-end actions sit on top of :mod:`engine.modules` and
:mod:`engine.registry`:

* :func:`install_upload` writes an uploaded file into the data folder (see
  :mod:`engine.paths`): a ``.json`` preset into ``presets/``, or a ``.zip`` of a
  module folder into ``sources/<type>/`` or ``sinks/<type>/``. A module only
  becomes selectable after the next sync.
* :func:`sync` is the *sync* button and the console's ``sync``: find the
  modules on disk, install their packages, re-import what changed. It reports
  what it printed, so the UI can show it.

A module zip holds one module folder, with its ``module.toml`` at the top, one
folder down (``joycon/module.toml``), or under its kind
(``sources/joycon/module.toml``). The folder name is the type; at the top level
the zip's own name is. Outside ``sources/``, the manifest must say
``kind = "source"`` or ``"sink"``.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import threading
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

from . import modules, paths, presets, registry
from .graph import Graph

MAX_UPLOAD = 64 << 20          # bytes per uploaded file
MAX_UNPACKED = 512 << 20       # bytes a module zip may expand to
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")   # imported as sources.<type>
_JUNK = ("__pycache__", "__MACOSX", ".DS_Store", ".git")

# Set by run.py: the --ext dirs, and whether --no-sync is in force.
EXTRA_DIRS: list = []
ENV_SYNC = True

_sync_lock = threading.Lock()


# ------------------------------------------------------------------------ upload
def install_upload(filename: str, data: bytes, source: str | None = None) -> dict:
    """Write an uploaded preset or module. A module gets an install record
    (``.install.json``, see :mod:`engine.modules`) naming *source*, by default
    ``upload:<filename>``."""
    if len(data) > MAX_UPLOAD:
        raise ValueError(f"{filename}: larger than {MAX_UPLOAD >> 20} MB")
    suffix = Path(filename).suffix.lower()
    if suffix == ".json":
        return _install_preset(filename, data)
    if suffix == ".zip":
        return _install_module(filename, data, source or f"upload:{Path(filename).name}")
    raise ValueError(f"{filename}: upload a module (.zip) or a preset (.json)")


def _install_preset(filename: str, data: bytes) -> dict:
    name = presets.check_name(Path(filename).stem)
    try:
        d = json.loads(data)
    except ValueError as e:
        raise ValueError(f"{filename}: not valid JSON ({e})") from None
    if not isinstance(d, dict) or not isinstance(d.get("connections"), list):
        raise ValueError(f"{filename}: not a preset (no \"connections\" list)")
    try:
        Graph.from_dict(d)            # unknown node types, missing ports, ...
    except Exception as e:
        raise ValueError(f"{filename}: {type(e).__name__}: {e}") from None
    d["name"] = name
    target = paths.PRESETS / f"{name}.json"
    replaced = target.exists()
    paths.PRESETS.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(d, indent=2))
    return {"kind": "preset", "name": name, "replaced": replaced,
            "missing": presets.missing(d)}


def _install_module(filename: str, data: bytes, source: str) -> dict:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError(f"{filename}: not a zip file") from None
    members = [i for i in zf.infolist()
               if not i.is_dir() and not any(j in PurePosixPath(i.filename).parts for j in _JUNK)]

    manifests = sorted((PurePosixPath(i.filename) for i in members
                        if PurePosixPath(i.filename).name == "module.toml"),
                       key=lambda p: len(p.parts))
    if not manifests:
        raise ValueError(f"{filename}: no module.toml inside")
    top = manifests[0].parent
    if sum(1 for m in manifests if len(m.parts) == len(manifests[0].parts)) > 1:
        raise ValueError(f"{filename}: holds more than one module; zip them one per file")
    if len(top.parts) > 2:
        raise ValueError(f"{filename}: module.toml is nested too deep ({manifests[0]})")

    name = top.name if top.parts else Path(filename).stem
    if not _IDENT.fullmatch(name):
        raise ValueError(f"{filename}: module name {name!r} must be a Python identifier "
                         "(letters, digits, _)")
    try:
        manifest = tomllib.loads(zf.read(str(manifests[0])).decode())
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"{filename}: module.toml: {e}") from None
    parent = top.parent.name if len(top.parts) == 2 else ""
    kind = paths.KINDS.get(parent) or manifest.get("kind")
    if kind not in paths.KINDS.values():
        raise ValueError(f"{filename}: say kind = \"source\" or \"sink\" in module.toml, "
                         "or zip it as sources/<type>/ or sinks/<type>/")

    files = []
    total = 0
    for info in members:
        rel = PurePosixPath(info.filename)
        if top.parts and rel.parts[:len(top.parts)] != top.parts:
            continue                  # outside the module folder
        rel = PurePosixPath(*rel.parts[len(top.parts):])
        if rel.is_absolute() or ".." in rel.parts or ":" in rel.parts[0]:
            raise ValueError(f"{filename}: unsafe path {info.filename!r}")
        if rel == PurePosixPath(modules.RECORD):
            continue                  # a zipped installed folder: write a fresh record
        total += info.file_size
        if total > MAX_UNPACKED:
            raise ValueError(f"{filename}: unpacks to more than {MAX_UNPACKED >> 20} MB")
        files.append((info, rel))
    try:
        entry = modules.check_entry(manifest.get("entry", modules.DEFAULT_ENTRY))
    except ValueError as e:
        raise ValueError(f"{filename}: module.toml: {e}") from None
    if not any(rel == PurePosixPath(entry) for _, rel in files):
        raise ValueError(f"{filename}: no {entry} (the module's entry) beside module.toml")

    dest_root = paths.upload_dir(kind)
    dest_root.mkdir(parents=True, exist_ok=True)
    dest = dest_root / name
    staging = dest_root / f".{name}.uploading"
    old = dest_root / f".{name}.old"
    for d in (staging, old):
        shutil.rmtree(d, ignore_errors=True)
    for info, rel in files:
        out = staging.joinpath(*rel.parts)
        out.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, out.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    version = str(manifest.get("version", ""))
    record = modules.write_record(staging, source, version, manifest.get("assets", []))
    replaced = dest.exists()
    if replaced:
        dest.rename(old)
    staging.rename(dest)
    shutil.rmtree(old, ignore_errors=True)
    return {"kind": "module", "name": name, "module_kind": kind, "replaced": replaced,
            "path": str(dest), "version": version, "digest": record["digest"]}


# -------------------------------------------------------------------------- sync
def sync(upgrade: bool = False) -> dict:
    """Re-read every module and preset on disk; install what modules need.

    Returns ``{"log": [...], "notes": [...], "sources": n, "sinks": n}``.
    """
    with _sync_lock, modules.capture() as log:
        enabled = modules.ensure(EXTRA_DIRS, sync=ENV_SYNC, upgrade=upgrade)
        registry.discover(enabled)
    return {"log": log, "notes": modules.system_notes(enabled),
            "sources": len(registry.SOURCES), "sinks": len(registry.SINKS)}

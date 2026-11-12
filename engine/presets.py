"""Preset files: their names, and the modules they need.

A preset addresses ports by bus namespace (``controller/gyro.y``, ``hid/mouse.dx``),
which is an *instance* id, not a plugin type: a real device and a stand-in for it
can both present the same namespace. So a preset records which types can fill each namespace it
uses, in a ``requires`` list written on every save::

    "requires": [
      {"id": "controller", "kind": "source", "types": ["controller", "controller_sim"]},
      {"id": "hid",        "kind": "sink",   "types": ["hid"]}
    ]

``types`` is the union of the type of whatever ran under that id when the preset
was saved, every installed type whose default id is that namespace, and what the
file already listed. A requirement is met when any of its types is installed and
available. A preset with no ``requires`` (hand-written, or older) is checked
against the namespaces its connections use instead.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re

from . import paths, registry
from .nodes import chain_inputs

# Also a file name: no separators, no leading dot.
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}")
BUILTIN = {"sys"}  # namespaces the engine provides itself


# ------------------------------------------------------------- install records
# A preset is one file, so its install record can't sit inside it the way a
# module's .install.json does: every preset's record lives in this one file in
# the presets folder, {name: {source, digest, catalog_sha256, installed}}.
# `digest` is the file as written; `catalog_sha256` the catalog's copy, so an
# update upstream and an edit here (Save in the UI) can be told apart.
RECORDS = ".install-records"


def _records_path():
    return paths.PRESETS / RECORDS


def read_records() -> dict:
    try:
        d = json.loads(_records_path().read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _write_records(records: dict):
    paths.PRESETS.mkdir(parents=True, exist_ok=True)
    _records_path().write_text(json.dumps(records, indent=2, sort_keys=True) + "\n")


def file_digest(name: str) -> str | None:
    try:
        return hashlib.sha256((paths.PRESETS / f"{name}.json").read_bytes()).hexdigest()
    except OSError:
        return None


def write_record(name: str, source: str, catalog_sha256: str | None = None) -> dict:
    records = read_records()
    records[name] = {"source": source, "digest": file_digest(name),
                     "catalog_sha256": catalog_sha256,
                     "installed": datetime.datetime.now(datetime.timezone.utc)
                     .isoformat(timespec="seconds")}
    _write_records(records)
    return records[name]


def forget_record(name: str):
    records = read_records()
    if records.pop(name, None) is not None:
        _write_records(records)


def check_name(name) -> str:
    name = str(name or "").strip()
    if not _NAME.fullmatch(name) or name.endswith("."):
        raise ValueError(f"bad preset name {name!r}: use letters, digits, space, . _ -")
    return name


def _registry(kind: str) -> dict:
    return registry.SOURCES if kind == "source" else registry.SINKS


def namespaces(preset: dict) -> dict[tuple[str, str], None]:
    """``{(kind, namespace)}`` that a preset's connections use, in order."""
    out: dict[tuple[str, str], None] = {}
    for c in preset.get("connections", []):
        ports = [("source", c.get("source", "")), ("sink", c.get("sink", "")),
                 *(("source", p) for p in chain_inputs(c.get("chain")))]
        for kind, port in ports:
            ns = str(port).partition("/")[0]
            if ns and ns not in BUILTIN:
                out[(kind, ns)] = None
    return out


def _types_for(kind: str, ns: str) -> set[str]:
    return {t for t, cls in _registry(kind).items() if getattr(cls, "id", t) == ns}


def derive_requires(preset: dict, running: dict[str, dict[str, str]],
                    previous: list | None = None) -> list[dict]:
    """The ``requires`` list to save with *preset*. ``running`` is
    ``{"source": {instance id: type}, "sink": {...}}``."""
    prev = {(r.get("kind"), r.get("id")): r for r in previous or [] if isinstance(r, dict)}
    out = []
    for kind, ns in namespaces(preset):
        types = set(prev.get((kind, ns), {}).get("types", []))
        if ns in running.get(kind, {}):
            types.add(running[kind][ns])
        types |= _types_for(kind, ns)
        out.append({"id": ns, "kind": kind, "types": sorted(types)})
    return out


def requirements(preset: dict) -> list[dict]:
    reqs = preset.get("requires")
    if isinstance(reqs, list):
        return [r for r in reqs if isinstance(r, dict) and r.get("id")]
    return [{"id": ns, "kind": kind, "types": sorted(_types_for(kind, ns))}
            for kind, ns in namespaces(preset)]


def missing(preset: dict) -> list[dict]:
    """Requirements no installed, runnable module meets — each with a ``reason``."""
    out = []
    for req in requirements(preset):
        kind = req.get("kind", "source")
        reg = _registry(kind)
        types = [str(t) for t in req.get("types", [])]
        installed = [t for t in types if t in reg]
        status = [(t, registry.availability(reg[t])) for t in installed]
        if any(ok for _, (ok, _) in status):
            continue
        if installed:
            t, (_, why) = status[0]
            reason = f"{t} is installed but unavailable: {why}" if why else f"{t} is unavailable"
        elif types:
            reason = f"install one of: {', '.join(types)}"
        else:
            reason = f"no installed {kind} provides '{req['id']}'"
        out.append({"id": req["id"], "kind": kind, "types": types, "reason": reason})
    return out

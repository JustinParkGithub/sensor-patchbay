"""Plugin registry — how a source or sink becomes selectable without editing
``run.py``, the engine, or the UI.

Two distinct names
------------------
Every plugin has a **type** and produces **instances**, and they are not the
same thing:

* ``type``  — the registry key, i.e. the entry you pick from the dropdown in the
  GUI or name on the command line (``joycon``, ``mock``, ``bmi160``, ``hid``,
  ``dryrun``, ...). It is one-class-per-type.
* ``id``    — the *default instance id*, which is the namespace every one of the
  plugin's ports is exposed under on the bus (``joycon/gyro.z``, ``hid/mouse.dx``).
  Presets reference ports by this namespace, so it must stay stable.

Keeping them separate is what lets a *stand-in* like the synthetic ``mock`` source
(``type="mock"``) share the real Joy-Con's bus namespace (``id="joycon"``): the
two are different registry entries but present the same ports, so a preset built
against one runs unchanged on the other. It is also what lets you run two of the
same board at once — a second instance is just given a suffixed id
(``bmi160``, ``bmi160-2``) by :class:`~engine.loop.EngineLoop`.

Discovery
---------
:func:`discover` imports each enabled module folder (``sources/<type>/``,
``sinks/<type>/``, extension dirs — see :mod:`engine.modules`) once, each in its
own ``try/except`` so one module's failure never blocks the others, which is
enough for the ``@register_source`` / ``@register_sink`` decorators to populate
:data:`SOURCES` / :data:`SINKS`. The folder name must equal the class's ``type``.

Calling it again (the UI's *sync* button) refreshes in place: new folders are
imported, folders whose files changed are re-imported, and types whose folder is
gone or disabled leave the menus. Instances already running keep running.

Availability
------------
A plugin whose Python module imports fine can still be unrunnable because an
*optional* dependency (``pynput``, ``pyjoycon``, ``pyserial``, ``RPi.GPIO``) is
missing. Plugins keep their heavy imports lazy (inside ``__init__``/``start``) so
they always register, and advertise a classmethod :meth:`available` → ``(ok,
reason)`` so the GUI and CLI can list them but grey out the ones that can't run
yet, with a reason, instead of hiding them entirely.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from pathlib import Path

SOURCES: dict[str, type] = {}
SINKS: dict[str, type] = {}


def _type_key(cls) -> str:
    """Registry key for a plugin class: its explicit ``type``, else its ``id``."""
    return getattr(cls, "type", None) or cls.id


def register_source(cls):
    SOURCES[_type_key(cls)] = cls
    return cls


def register_sink(cls):
    SINKS[_type_key(cls)] = cls
    return cls


# --------------------------------------------------------------------- discovery
def extension_dirs() -> list[Path]:
    """Directories of module folders kept outside the repo.

    The repo's own ``sources/`` and ``sinks/`` are the main drop-in folders; these
    are scanned too: every path in the ``PATCHBAY_EXT_PATH`` env var
    (os.pathsep-separated), plus whatever ``--ext`` passes to
    :func:`engine.modules.find_modules`.
    """
    return [Path(raw.strip()) for raw in os.environ.get("PATCHBAY_EXT_PATH", "").split(os.pathsep)
            if raw.strip()]


def _import_name(mod) -> str:
    return f"{mod.kind}s.{mod.name}" if not mod.external else f"patchbay_ext_{mod.name}"


def _import_module(mod) -> None:
    """Import one :class:`engine.modules.Module` so its decorators run."""
    if not mod.external:
        importlib.import_module(_import_name(mod))
        return
    # An out-of-repo folder isn't on sys.path; load it as a package by file path.
    name = _import_name(mod)
    spec = importlib.util.spec_from_file_location(
        name, mod.path / "__init__.py", submodule_search_locations=[str(mod.path)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)


def _fingerprint(mod) -> tuple:
    """What a module's code looked like when imported: path, mtime, size per file."""
    out = []
    for p in sorted(mod.path.rglob("*")):
        if p.suffix in (".py", ".toml") and "__pycache__" not in p.parts and p.is_file():
            st = p.stat()
            out.append((str(p.relative_to(mod.path)), st.st_mtime_ns, st.st_size))
    return tuple(out)


# module name -> (import name, fingerprint, registry, types it registered)
_LOADED: dict[str, tuple[str, tuple, dict, list[str]]] = {}


def _forget(name: str):
    import_name, _, registry, types = _LOADED.pop(name)
    for key in [k for k in sys.modules if k == import_name or k.startswith(import_name + ".")]:
        del sys.modules[key]
    for t in types:
        registry.pop(t, None)


def discover(modules: list | None = None):
    """Import each enabled module (from :func:`engine.modules.ensure`) so its
    ``@register_*`` decorator runs. With no list, every module found on disk.

    Safe to call more than once; see *Discovery* above for what a second call
    does. A module that fails to import is reported and skipped — it never
    registers, and stays out of the menus rather than fatal.
    """
    from engine import paths
    from engine.modules import _say, find_modules

    if modules is None:
        modules = find_modules()
    paths.extend_packages()
    importlib.invalidate_caches()   # see folders written since the last import

    wanted = {m.name: m for m in modules}
    for name, (import_name, fp, _, _) in list(_LOADED.items()):
        mod = wanted.get(name)
        if mod is None:
            _forget(name)
            _say(f"[modules] {name}: removed")
        elif _import_name(mod) != import_name or _fingerprint(mod) != fp:
            _forget(name)
            _say(f"[modules] {name}: changed, reloading")

    for mod in modules:
        if mod.name in _LOADED:
            continue
        registry = SOURCES if mod.kind == "source" else SINKS
        import_name = _import_name(mod)
        fp = _fingerprint(mod)
        try:
            _import_module(mod)
        except Exception as e:
            _say(f"[modules] {mod.name}: failed to import ({type(e).__name__}: {e})")
            continue
        # by defining module, not by what appeared: importing a `depends` module
        # registers *its* type while this one loads
        types = [t for t, cls in registry.items()
                 if cls.__module__ == import_name or cls.__module__.startswith(import_name + ".")]
        _LOADED[mod.name] = (import_name, fp, registry, types)
        if mod.name not in registry:
            _say(f"[modules] {mod.name}: folder name doesn't match any registered "
                 f"{mod.kind} type (registered: {sorted(registry)})")
    return SOURCES, SINKS


# ------------------------------------------------------------------ instantiation
def parse_spec(spec: str) -> tuple[str, dict]:
    """``"type:k=v,k2=v2"`` -> ``("type", {"k": "v", "k2": "v2"})``."""
    name, _, argstr = spec.partition(":")
    kwargs = {}
    for pair in argstr.split(","):
        if not pair:
            continue
        k, _, v = pair.partition("=")
        kwargs[k] = v
    return name.strip(), kwargs


def _coerce(argspec: dict | None, value):
    """Coerce one constructor arg to the type declared in the class's ``ARGS``.

    CLI args always arrive as strings and are coerced by ``ARGS[k]["type"]``.
    API args arrive already typed from JSON (int/float/bool) and are trusted as-is
    unless the target is ``str``. Coercion that raises falls back to the raw value.
    """
    typ = (argspec or {}).get("type", str)
    if value is None:
        return None
    if not isinstance(value, str):
        return value if typ is not str else str(value)
    try:
        return typ(value)
    except Exception:
        return value


def build(registry: dict, type_name: str, kwargs: dict | None = None,
          instance_id: str | None = None):
    """Instantiate a registered plugin by *type_name*.

    Returns ``(instance_id, instance)``. ``instance_id`` is the caller's override
    if given, else the instance's own ``.id`` (its default bus namespace).
    """
    cls = registry.get(type_name)
    if cls is None:
        raise KeyError(
            f"no plugin registered as {type_name!r}; available: {sorted(registry)}")
    argspecs = getattr(cls, "ARGS", {})
    coerced = {k: _coerce(argspecs.get(k), v) for k, v in (kwargs or {}).items()}
    inst = cls(**coerced)
    return (instance_id or getattr(inst, "id", type_name)), inst


def build_spec(registry: dict, spec: str, instance_id: str | None = None):
    """Instantiate from a ``"type:k=v,..."`` CLI spec. See :func:`build`."""
    type_name, kwargs = parse_spec(spec)
    return build(registry, type_name, kwargs, instance_id)


# --------------------------------------------------------------------- inspection
def availability(cls) -> tuple[bool, str]:
    """Normalise a plugin's ``available()`` classmethod to ``(ok, reason)``.

    A plugin may return a bool, an ``(ok, reason)`` pair, or omit the method
    entirely (assumed available). Any exception counts as unavailable.
    """
    fn = getattr(cls, "available", None)
    if fn is None:
        return True, ""
    try:
        res = fn()
    except Exception as e:  # pragma: no cover - defensive
        return False, str(e)
    if isinstance(res, tuple):
        ok, reason = (list(res) + [""])[:2]
        return bool(ok), str(reason)
    return bool(res), ""


def _type_name(typ) -> str:
    """Name the arg's coercion type so a GUI can pick an input widget."""
    if typ in (int,):
        return "int"
    if typ in (float,):
        return "float"
    if typ in (str,) or typ is None:
        return "str"
    return "bool"  # bool() or a truthy-string lambda (an on/off ARG)


def catalog(registry: dict, kind: str) -> list[dict]:
    """Machine-readable listing for the GUI dropdown and the CLI.

    One dict per registered *type*: its label, its default bus id, whether it can
    run right now (and why not), and the constructor args it accepts.
    """
    out = []
    for type_name, cls in sorted(registry.items()):
        ok, reason = availability(cls)
        args = []
        for name, spec in getattr(cls, "ARGS", {}).items():
            args.append({
                "name": name,
                "default": spec.get("default"),
                "type": _type_name(spec.get("type", str)),
                "help": spec.get("help", ""),
            })
        out.append({
            "type": type_name,
            "label": getattr(cls, "label", type_name),
            "kind": kind,
            "default_id": getattr(cls, "id", type_name),
            "available": ok,
            "reason": reason,
            "args": args,
        })
    return out


def describe(registry: dict) -> str:
    """Human-readable listing for ``--list-sources`` / ``--list-sinks``."""
    lines = []
    for entry in catalog(registry, ""):
        mark = "" if entry["available"] else f"  (unavailable: {entry['reason']})"
        lines.append(f"{entry['type']:14} {entry['label']}{mark}")
        for a in entry["args"]:
            lines.append(f"  {a['name']}={a['default']!r:<10} {a['help']}")
    return "\n".join(lines) if lines else "(none registered)"

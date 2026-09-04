"""Plugin registry: how a new source or sink becomes usable without editing
``run.py``.

A plugin class registers itself by decorating with ``@register_source`` or
``@register_sink`` at module scope. ``discover()`` imports every module under
``plugins/`` and ``sinks/`` once (each in its own try/except, so one plugin's
missing dependency — no ``pyserial``, say — never blocks the others) which is
enough to populate ``SOURCES`` / ``SINKS`` by the class's ``id``. From there:

    * ``--list-sources`` / ``--list-sinks`` introspect what's available and
      what constructor args each one takes (its ``ARGS`` dict).
    * ``--source NAME[:k=v,k2=v2]`` / ``--sink NAME[:k=v,...]`` in ``run.py``
      instantiate any registered plugin by name, coercing args per ``ARGS``.

Adding a new sensor or output is then: write ``plugins/foo.py`` (or
``sinks/foo.py``) subclassing ``Source``/``Sink``, decorate the class, done —
it shows up in ``--list-sources`` and is selectable via ``--source foo`` with
no other file touched. ``joycon_r``/``mock`` and ``mouse_keyboard``/``null``/
``generic_out`` are registered the same way; ``run.py`` keeps its old
``--mock``/``--dry-run``/``--robot`` flags as convenience wrappers over this.
"""

from __future__ import annotations

import importlib
import pkgutil

SOURCES: dict[str, type] = {}
SINKS: dict[str, type] = {}


def register_source(cls):
    SOURCES[cls.id] = cls
    return cls


def register_sink(cls):
    SINKS[cls.id] = cls
    return cls


def discover():
    """Import every module under plugins/ and sinks/ so decorators run.

    Safe to call more than once. A module that fails to import (missing
    third-party dependency, unsupported platform, ...) is skipped silently —
    it just never registers, and stays unavailable rather than fatal.
    """
    import plugins as _plugins_pkg
    import sinks as _sinks_pkg

    for pkg in (_plugins_pkg, _sinks_pkg):
        for _, modname, _ in pkgutil.iter_modules(pkg.__path__, pkg.__name__ + "."):
            try:
                importlib.import_module(modname)
            except Exception:
                pass
    return SOURCES, SINKS


def parse_spec(spec: str) -> tuple[str, dict]:
    """``"name:k=v,k2=v2"`` -> ``("name", {"k": "v", "k2": "v2"})``."""
    name, _, argstr = spec.partition(":")
    kwargs = {}
    for pair in argstr.split(","):
        if not pair:
            continue
        k, _, v = pair.partition("=")
        kwargs[k] = v
    return name, kwargs


def instantiate(registry: dict, spec: str):
    """Build a registered source/sink from a ``"name:k=v,..."`` CLI spec.

    Every value arrives as a string; it's coerced using the ``type`` named in
    the class's ``ARGS[k]`` (default ``str``) before the constructor sees it.
    """
    name, raw_kwargs = parse_spec(spec)
    cls = registry.get(name)
    if cls is None:
        raise KeyError(f"no plugin registered as {name!r}; available: {sorted(registry)}")
    argspecs = getattr(cls, "ARGS", {})
    kwargs = {}
    for k, v in raw_kwargs.items():
        argspec = argspecs.get(k, {})
        typ = argspec.get("type", str)
        kwargs[k] = typ(v)
    return cls(**kwargs)


def describe(registry: dict) -> str:
    """Human-readable listing for --list-sources / --list-sinks."""
    lines = []
    for id_, cls in sorted(registry.items()):
        lines.append(f"{id_:14} {cls.label}")
        for name, spec in getattr(cls, "ARGS", {}).items():
            default = spec.get("default", None)
            help_ = spec.get("help", "")
            lines.append(f"  {name}={default!r:<10} {help_}")
    return "\n".join(lines) if lines else "(none registered)"

# Extensions

Drop a `.py` file in this directory to add a new **source** or **sink** to the
patchbay. Nothing else — no install step, no editing the engine, `run.py`, or the
UI. On the next start, `engine.registry.discover()` imports every `*.py` here
(files starting with `_` are skipped), the `@register_source` / `@register_sink`
decorator runs, and the plugin shows up:

* in the GUI's **add source / add sink** dropdown,
* in `python run.py --list-sources` / `--list-sinks`,
* on the `--source` / `--sink` command-line flags,
* in the `--cli` console's `add` command.

You can also point the loader at directories outside the repo:

```bash
python run.py --ext ~/patchbay-plugins --ext /opt/site/plugins
export PATCHBAY_EXT_PATH=~/patchbay-plugins   # colon-separated, honoured every run
```

## Writing one

A source subclasses `plugins.base.Source` and returns `{port_id: float}` from
`read()`. A sink subclasses `sinks.base.Sink` and acts on the `{port_id: float}`
dict passed to `apply()`. Give the class a `type` (the dropdown key), an `id`
(the bus namespace its ports live under), a `label`, and an `ARGS` dict declaring
its constructor arguments so the GUI can build a form and the CLI can coerce
values. Import any third-party dependency **lazily** (inside `__init__`/`start`)
and override `available()` so the picker greys it out with a reason when the
dependency is missing, instead of failing to load. See `example_gpio_sink.py`
here and the fuller contract in [`docs/SPECIFICATION.md`](../docs/SPECIFICATION.md).

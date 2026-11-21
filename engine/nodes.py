"""Transform nodes. Each node is a tiny stateful DSP block that sits on a cable.

A node implements ``process(x: float, dt: float) -> float`` and ``reset()``.
``NODE_SPECS`` describes the parameters so the web UI can build an editor with no
hard-coded knowledge of any particular node.

A node with ``{"port": "source"}`` parameters also reads those ports off the
bus: before each ``process`` call the connection copies each one's value into
``node.inputs[param name]`` (see :class:`Combine` and :class:`Chord`).
"""

from __future__ import annotations

import math


class Node:
    type = "identity"

    def __init__(self, **params):
        self.params = params
        # {param name: bus port} for this node's port-typed params that are set;
        # the connection fills self.inputs from them each tick.
        self.input_ports = {
            name: str(params[name])
            for name, spec in NODE_SPECS.get(self.type, {}).items()
            if isinstance(spec, dict) and "port" in spec and params.get(name)
        }
        self.inputs = {name: 0.0 for name in self.input_ports}

    def process(self, x: float, dt: float) -> float:
        return x

    def reset(self):
        pass


class Scale(Node):
    type = "scale"

    def process(self, x, dt):
        return x * float(self.params.get("factor", 1.0))


class Offset(Node):
    type = "offset"

    def process(self, x, dt):
        return x + float(self.params.get("amount", 0.0))


class Invert(Node):
    type = "invert"

    def process(self, x, dt):
        return -x


class Abs(Node):
    type = "abs"

    def process(self, x, dt):
        return abs(x)


class Clamp(Node):
    type = "clamp"

    def process(self, x, dt):
        lo = float(self.params.get("lo", -1.0))
        hi = float(self.params.get("hi", 1.0))
        return max(lo, min(hi, x))


class Deadzone(Node):
    type = "deadzone"

    def process(self, x, dt):
        t = float(self.params.get("threshold", 0.05))
        if abs(x) <= t:
            return 0.0
        s = 1.0 if x > 0 else -1.0
        span = 1.0 - t
        return s * (abs(x) - t) / span if span > 1e-9 else s * (abs(x) - t)


class Expo(Node):
    """Blend between linear and cubic response. amount 0 = linear, 1 = full cubic."""
    type = "expo"

    def process(self, x, dt):
        a = float(self.params.get("amount", 0.5))
        return (1.0 - a) * x + a * x * x * x


class Quantize(Node):
    type = "quantize"

    def process(self, x, dt):
        step = float(self.params.get("step", 0.1))
        return round(x / step) * step if step > 1e-9 else x


class EMA(Node):
    type = "ema"

    def __init__(self, **p):
        super().__init__(**p)
        self.y = None

    def reset(self):
        self.y = None

    def process(self, x, dt):
        a = float(self.params.get("alpha", 0.2))
        if self.y is None:
            self.y = x
        self.y += a * (x - self.y)
        return self.y


class OneEuro(Node):
    """1-euro filter: smooth when still, responsive when moving. Great for motion."""
    type = "one_euro"

    def __init__(self, **p):
        super().__init__(**p)
        self.x_prev = None
        self.dx_prev = 0.0

    def reset(self):
        self.x_prev = None
        self.dx_prev = 0.0

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2.0 * math.pi * max(cutoff, 1e-6))
        return 1.0 / (1.0 + tau / dt)

    def process(self, x, dt):
        if dt <= 0:
            return x
        min_cutoff = float(self.params.get("min_cutoff", 1.0))
        beta = float(self.params.get("beta", 0.02))
        d_cutoff = float(self.params.get("d_cutoff", 1.0))
        if self.x_prev is None:
            self.x_prev = x
            return x
        dx = (x - self.x_prev) / dt
        a_d = self._alpha(d_cutoff, dt)
        dx_hat = a_d * dx + (1 - a_d) * self.dx_prev
        cutoff = min_cutoff + beta * abs(dx_hat)
        a = self._alpha(cutoff, dt)
        x_hat = a * x + (1 - a) * self.x_prev
        self.x_prev = x_hat
        self.dx_prev = dx_hat
        return x_hat


class RateLimit(Node):
    """Slew limiter: output can move at most `per_sec` units per second."""
    type = "rate_limit"

    def __init__(self, **p):
        super().__init__(**p)
        self.y = 0.0

    def reset(self):
        self.y = 0.0

    def process(self, x, dt):
        mx = float(self.params.get("per_sec", 5.0)) * dt
        d = x - self.y
        d = max(-mx, min(mx, d))
        self.y += d
        return self.y


class Threshold(Node):
    """scalar -> gate. mode 'gt' => 1 when x > level, 'lt' => 1 when x < level."""
    type = "threshold"

    def process(self, x, dt):
        level = float(self.params.get("level", 0.5))
        if self.params.get("mode", "gt") == "lt":
            return 1.0 if x < level else 0.0
        return 1.0 if x > level else 0.0


class Schmitt(Node):
    """Hysteresis gate. If on >= off it triggers high; if on < off it triggers low
    (i.e. a "less-than" gate). Output is a latched 0/1 level."""
    type = "schmitt"

    def __init__(self, **p):
        super().__init__(**p)
        self.state = 0.0

    def reset(self):
        self.state = 0.0

    def process(self, x, dt):
        on = float(self.params.get("on", 0.6))
        off = float(self.params.get("off", 0.4))
        if on >= off:
            if x >= on:
                self.state = 1.0
            elif x <= off:
                self.state = 0.0
        else:
            if x <= on:
                self.state = 1.0
            elif x >= off:
                self.state = 0.0
        return self.state


class Debounce(Node):
    """Rising-edge -> single pulse, then a lockout of `ms` milliseconds."""
    type = "debounce"

    def __init__(self, **p):
        super().__init__(**p)
        self.clock = 0.0
        self.last = -1e9
        self.prev = 0.0

    def reset(self):
        self.clock = 0.0
        self.last = -1e9
        self.prev = 0.0

    def process(self, x, dt):
        self.clock += dt
        ms = float(self.params.get("ms", 300.0))
        hi = x >= 0.5
        out = 0.0
        if hi and self.prev < 0.5 and (self.clock - self.last) * 1000.0 >= ms:
            out = 1.0
            self.last = self.clock
        self.prev = 1.0 if hi else 0.0
        return out


class Toggle(Node):
    """Rising edge flips a latched 0/1 state."""
    type = "toggle"

    def __init__(self, **p):
        super().__init__(**p)
        self.state = float(p.get("initial", 0.0))
        self.prev = 0.0

    def reset(self):
        self.state = float(self.params.get("initial", 0.0))
        self.prev = 0.0

    def process(self, x, dt):
        if x >= 0.5 and self.prev < 0.5:
            self.state = 1.0 - self.state
        self.prev = x
        return self.state


class Hold(Node):
    """Stretch a pulse/gate so it stays high for at least `ms` after going high."""
    type = "hold"

    def __init__(self, **p):
        super().__init__(**p)
        self.clock = 0.0
        self.until = -1e9

    def reset(self):
        self.clock = 0.0
        self.until = -1e9

    def process(self, x, dt):
        self.clock += dt
        ms = float(self.params.get("ms", 120.0))
        if x >= 0.5:
            self.until = self.clock + ms / 1000.0
        return 1.0 if self.clock < self.until else 0.0


class Combine(Node):
    """Merge the cable's signal with a second source port (``input``).

    gate    x while the other port is on, else 0 (e.g. gyro only while a button is held)
    unless  x while the other port is off, else 0
    add, mul, min, max   arithmetic on the two values
    and, or              0/1 gate from x and the other port

    "On" means ``>= level``. An unset or absent port reads as 0, so a ``gate``
    stays closed until its other source exists.
    """
    type = "combine"

    def reset(self):
        self.inputs = {name: 0.0 for name in self.input_ports}

    def process(self, x, dt):
        y = self.inputs.get("input", 0.0)
        op = self.params.get("op", "gate")
        level = float(self.params.get("level", 0.5))
        if op == "gate":
            return x if y >= level else 0.0
        if op == "unless":
            return 0.0 if y >= level else x
        if op == "add":
            return x + y
        if op == "mul":
            return x * y
        if op == "min":
            return min(x, y)
        if op == "max":
            return max(x, y)
        if op == "and":
            return 1.0 if x >= level and y >= level else 0.0
        if op == "or":
            return 1.0 if x >= level or y >= level else 0.0
        return x


class Chord(Node):
    """Two-button combo over buttons A and B (``input``).

    Which button is A, and what the cable carries, depends on ``trigger``:

    unset    A is this cable's own signal and the output is a 0/1 gate: the
             combo *is* the signal (press A+B -> press a key).
    set      A is the ``trigger`` port and the cable's signal passes through
             untouched while the role is active, else 0. The combo only decides
             *when*; the source decides *what* (hold A+B -> stick drives the
             mouse). Nodes after the chord shape it as on any other cable.

    A combo is up to three cables, each with a chord node naming the other
    button and the same ``window_ms``: A alone (role ``solo``), B alone
    (``solo``, buttons swapped) and A+B (``both``). Every chord node runs the
    same state machine over the pair, so they always agree on what happened.

    solo   1 while A is held *on its own*. A press waits up to ``window_ms`` for B;
           if B joins, it's a chord and A's solo never fires. A tap shorter than
           the window still fires, as a one-tick pulse on release. A press that
           lands while B is already held (from outside the window) is solo at once.
    both   1 while the chord is held: both pressed within ``window_ms`` of each
           other. When one is let go the chord ends, and the one still held is
           spent: it fires nothing until released. While it's held, pressing the
           other again re-forms the chord (hold B, tap A repeatedly).

    "Pressed" means ``>= level``. The cost of the window is latency: a solo
    action starts ``window_ms`` after the press.
    """
    type = "chord"

    UP, WAIT, SOLO, CHORD, SPENT = range(5)

    def __init__(self, **p):
        super().__init__(**p)
        self.reset()

    def reset(self):
        self.inputs = {name: 0.0 for name in self.input_ports}
        self.clock = 0.0
        self.a = self.b = self.UP          # status of this button / the partner
        self.ta = self.tb = 0.0            # when each went into WAIT
        self.prev_a = self.prev_b = False

    def _step(self, a, b, dt):
        """Advance the pair. Returns True if A was tapped (released while waiting)."""
        UP, WAIT, SOLO, CHORD, SPENT = self.UP, self.WAIT, self.SOLO, self.CHORD, self.SPENT
        self.clock += dt
        window = max(0.0, float(self.params.get("window_ms", 60.0))) / 1000.0
        rise_a, rise_b = a and not self.prev_a, b and not self.prev_b
        self.prev_a, self.prev_b = a, b
        tapped = False

        # releases: a chord broken by one side leaves the other spent
        if not a and self.a != UP:
            tapped = self.a == WAIT
            if self.a == CHORD and self.b == CHORD:
                self.b = SPENT
            self.a = UP
        if not b and self.b != UP:
            if self.b == CHORD and self.a == CHORD:
                self.a = SPENT
            self.b = UP

        # presses
        if rise_a and rise_b:
            self.a = self.b = CHORD
        elif rise_a:
            if self.b in (WAIT, SPENT, CHORD):
                self.a = self.b = CHORD
            elif self.b == SOLO:
                self.a = SOLO
            else:
                self.a, self.ta = WAIT, self.clock
        elif rise_b:
            if self.a in (WAIT, SPENT, CHORD):
                self.a = self.b = CHORD
            elif self.a == SOLO:
                self.b = SOLO
            else:
                self.b, self.tb = WAIT, self.clock

        # the window ran out with nobody joining
        if self.a == WAIT and self.clock - self.ta >= window:
            self.a = SOLO
        if self.b == WAIT and self.clock - self.tb >= window:
            self.b = SOLO
        return tapped

    def process(self, x, dt):
        level = float(self.params.get("level", 0.5))
        passthrough = "trigger" in self.input_ports
        a = self.inputs["trigger"] if passthrough else x
        tapped = self._step(a >= level, self.inputs.get("input", 0.0) >= level, dt)
        if self.params.get("role", "solo") == "both":
            on = self.a == self.CHORD
        else:
            on = self.a == self.SOLO or tapped
        if passthrough:
            return x if on else 0.0
        return 1.0 if on else 0.0


NODE_CLASSES = {
    c.type: c for c in (
        Scale, Offset, Invert, Abs, Clamp, Deadzone, Expo, Quantize,
        EMA, OneEuro, RateLimit, Threshold, Schmitt, Debounce, Toggle, Hold, Combine,
        Chord,
    )
}

# Parameter descriptions for the UI. {name: [default, min, max, step]},
# {name: {"choices": [...]}} for enums, or {name: {"port": "source"}} for a
# second input read off the bus.
NODE_SPECS = {
    "scale":      {"factor": [1.0, -100.0, 100.0, 0.1]},
    "offset":     {"amount": [0.0, -10.0, 10.0, 0.01]},
    "invert":     {},
    "abs":        {},
    "clamp":      {"lo": [-1.0, -100.0, 100.0, 0.1], "hi": [1.0, -100.0, 100.0, 0.1]},
    "deadzone":   {"threshold": [0.05, 0.0, 1.0, 0.01]},
    "expo":       {"amount": [0.5, 0.0, 1.0, 0.05]},
    "quantize":   {"step": [0.1, 0.001, 10.0, 0.01]},
    "ema":        {"alpha": [0.2, 0.001, 1.0, 0.01]},
    "one_euro":   {"min_cutoff": [1.0, 0.01, 20.0, 0.05], "beta": [0.02, 0.0, 2.0, 0.005]},
    "rate_limit": {"per_sec": [5.0, 0.1, 200.0, 0.5]},
    "threshold":  {"level": [0.5, -10.0, 10.0, 0.01], "mode": {"choices": ["gt", "lt"]}},
    "schmitt":    {"on": [0.6, -180.0, 180.0, 0.5], "off": [0.4, -180.0, 180.0, 0.5]},
    "debounce":   {"ms": [300.0, 10.0, 5000.0, 10.0]},
    "toggle":     {"initial": [0.0, 0.0, 1.0, 1.0]},
    "hold":       {"ms": [120.0, 10.0, 5000.0, 10.0]},
    "combine":    {"op": {"choices": ["gate", "unless", "add", "mul", "min", "max", "and", "or"]},
                   "input": {"port": "source"},
                   "level": [0.5, -180.0, 180.0, 0.05]},
    "chord":      {"role": {"choices": ["solo", "both"]},
                   "trigger": {"port": "source"},
                   "input": {"port": "source"},
                   "window_ms": [60.0, 0.0, 1000.0, 5.0],
                   "level": [0.5, -180.0, 180.0, 0.05]},
}


def chain_inputs(chain: list | None) -> list[str]:
    """The extra source ports a serialised chain reads (``combine``/``chord`` inputs)."""
    ports = []
    for node in chain or []:
        for name, spec in NODE_SPECS.get(node.get("type"), {}).items():
            value = (node.get("params") or {}).get(name)
            if isinstance(spec, dict) and "port" in spec and value:
                ports.append(str(value))
    return ports


def make_node(type_: str, params: dict | None = None) -> Node:
    cls = NODE_CLASSES.get(type_)
    if cls is None:
        raise ValueError(f"unknown node type {type_!r}")
    return cls(**(params or {}))

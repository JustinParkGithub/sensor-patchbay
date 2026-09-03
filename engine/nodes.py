"""Transform nodes. Each node is a tiny stateful DSP block that sits on a cable.

A node implements ``process(x: float, dt: float) -> float`` and ``reset()``.
``NODE_SPECS`` describes the parameters so the web UI can build an editor with no
hard-coded knowledge of any particular node.
"""

from __future__ import annotations

import math


class Node:
    type = "identity"

    def __init__(self, **params):
        self.params = params

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


NODE_CLASSES = {
    c.type: c for c in (
        Scale, Offset, Invert, Abs, Clamp, Deadzone, Expo, Quantize,
        EMA, OneEuro, RateLimit, Threshold, Schmitt, Debounce, Toggle, Hold,
    )
}

# Parameter descriptions for the UI. {name: [default, min, max, step]} or
# {name: {"choices": [...]}} for enums.
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
}


def make_node(type_: str, params: dict | None = None) -> Node:
    cls = NODE_CLASSES.get(type_)
    if cls is None:
        raise ValueError(f"unknown node type {type_!r}")
    return cls(**(params or {}))

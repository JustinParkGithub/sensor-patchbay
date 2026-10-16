"""Webcam hand tracking + gesture recognition (MediaPipe), as a patchbay source.

The same MediaPipe ``GestureRecognizer`` as ``tracker_templates/gesture_tracker.py``
(which also yields the 21 hand landmarks ``hand_tracker.py`` uses), wrapped
in the ``Source`` contract: the camera and the model run on their own thread, and
``read()`` just hands back the latest flat dict of ports.

Self-contained: nothing in the engine, server or UI knows about it. It is just
another registered source, added like any other — from the GUI's *add source*
picker, ``--source cv:camera=1``, or the ``--cli`` console's ``add`` — and
removed the same way.

Needs the optional extras in ``requirements-cv.txt`` (``opencv-python`` +
``mediapipe``) and the model file at ``task/gesture_recognizer.task`` (override
with ``model=``). Both libraries are imported lazily, so the plugin registers
without them and :meth:`HandGestureCV.available` greys it out in the picker with
the reason instead.
"""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path

from engine.registry import register_source
from engine.signals import EVENT, SCALAR, PortSpec
from plugins.base import Source

DEFAULT_MODEL = Path(__file__).resolve().parent.parent / "task" / "gesture_recognizer.task"

# MediaPipe's canned gesture classes -> port ids. "None" (no gesture) gets no port.
GESTURES = {
    "Closed_Fist": "gesture.fist",
    "Open_Palm": "gesture.palm",
    "Pointing_Up": "gesture.point",
    "Thumb_Up": "gesture.thumb_up",
    "Thumb_Down": "gesture.thumb_down",
    "Victory": "gesture.victory",
    "ILoveYou": "gesture.ily",
}

# Landmark indices (see MediaPipe hand landmark docs).
WRIST, THUMB_TIP, INDEX_TIP, MIDDLE_MCP = 0, 4, 8, 9

PORTS = [
    PortSpec("hand.present", EVENT, "hand.present", "hand", hint="1 while a hand is tracked"),
    PortSpec("hand.x", SCALAR, "hand.x", "hand", hint="index tip, -1 (left) .. 1 (right), mirrored"),
    PortSpec("hand.y", SCALAR, "hand.y", "hand", hint="index tip, -1 (bottom) .. 1 (top)"),
    PortSpec("hand.pinch", SCALAR, "hand.pinch", "hand",
             hint="thumb-index gap / palm size; ~0 pinched, ~1+ open"),
    *[PortSpec(pid, EVENT, pid, "gesture", hint=name.replace("_", " ").lower())
      for name, pid in GESTURES.items()],
    PortSpec("gesture.score", SCALAR, "gesture.score", "gesture", hint="confidence of the top gesture"),
]


@register_source
class HandGestureCV(Source):
    type = "cv"
    id = "cv"
    label = "Hand tracker (camera)"
    PORTS = PORTS

    @classmethod
    def available(cls):
        try:
            import cv2  # noqa: F401
            import mediapipe  # noqa: F401
        except Exception as e:
            return False, f"needs opencv-python + mediapipe — pip install -r requirements-cv.txt ({e})"
        return True
    ARGS = {
        "camera": {"default": 0, "type": int, "help": "OpenCV camera index"},
        "model": {"default": str(DEFAULT_MODEL), "type": str,
                  "help": "path to gesture_recognizer.task"},
        "min_score": {"default": 0.5, "type": float,
                      "help": "gesture confidence needed to fire a gesture.* port"},
    }

    def __init__(self, camera=0, model=str(DEFAULT_MODEL), min_score=0.5):
        import cv2  # lazy: optional deps (see available())
        import mediapipe as mp
        from mediapipe.tasks.python import vision

        self._cv2, self._mp = cv2, mp
        self._min_score = min_score
        self._lock = threading.Lock()
        self._latest = self._idle()
        self._stop = threading.Event()
        self._thread = None
        self._status = "starting"

        if not Path(model).is_file():
            raise FileNotFoundError(f"MediaPipe model not found at {model}")
        opts = vision.GestureRecognizerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=model),
            num_hands=1,
            running_mode=vision.RunningMode.VIDEO,
        )
        self._recognizer = vision.GestureRecognizer.create_from_options(opts)

        # Open eagerly so a missing camera / denied permission fails the
        # request that asked for it, instead of a silent "ok" module.
        self._cap = cv2.VideoCapture(int(camera))
        if not self._cap.isOpened():
            self._recognizer.close()
            raise RuntimeError(f"could not open camera {camera} (on macOS, grant the "
                               "terminal camera access in System Settings > Privacy)")

    def start(self):
        self._thread = threading.Thread(target=self._poll, name="cv", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._cap.release()
        self._recognizer.close()

    def status(self):
        return self._status

    def read(self):
        with self._lock:
            return dict(self._latest)

    # ------------------------------------------------------------------
    @staticmethod
    def _idle():
        return {p.id: 0.0 for p in PORTS}

    def _poll(self):
        cv2, mp = self._cv2, self._mp
        t0 = time.monotonic()
        while not self._stop.is_set():
            ok, frame = self._cap.read()
            if not ok:
                self._status = "error: camera read failed"
                time.sleep(0.2)
                continue
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            ts_ms = int((time.monotonic() - t0) * 1000)  # VIDEO mode needs it monotonic
            try:
                result = self._recognizer.recognize_for_video(image, ts_ms)
            except Exception as e:
                self._status = f"error: {e}"
                continue
            out = self._ingest(result)
            self._status = "ok" if out["hand.present"] else "ok · no hand"
            with self._lock:
                self._latest = out

    def _ingest(self, result) -> dict:
        out = self._idle()
        if not result.hand_landmarks:
            return out
        lm = result.hand_landmarks[0]
        tip = lm[INDEX_TIP]
        out["hand.present"] = 1.0
        # Camera frames aren't mirrored: moving your hand right moves it left in
        # the image, so flip x to match what you see in a selfie view.
        out["hand.x"] = (0.5 - tip.x) * 2.0
        out["hand.y"] = (0.5 - tip.y) * 2.0
        palm = math.dist((lm[WRIST].x, lm[WRIST].y), (lm[MIDDLE_MCP].x, lm[MIDDLE_MCP].y))
        gap = math.dist((lm[THUMB_TIP].x, lm[THUMB_TIP].y), (tip.x, tip.y))
        out["hand.pinch"] = gap / palm if palm > 1e-6 else 0.0

        if result.gestures and result.gestures[0]:
            top = result.gestures[0][0]
            out["gesture.score"] = top.score
            pid = GESTURES.get(top.category_name)
            if pid and top.score >= self._min_score:
                out[pid] = 1.0
        return out

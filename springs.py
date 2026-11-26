# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Spring motion for the interface, in the spirit of web animation libraries like Motion (motion.dev): things
move like they have a little weight. They speed up, overshoot a touch and settle, instead of sliding at a
fixed speed or jumping.

    Spring          the physics: a value pulled toward a target by a spring and slowed by damping
    Animator        runs springs on a Tk widget at about 60 fps and stops by itself once they settle
    animations_on   False when Windows' "Animation effects" setting is off; everything then jumps straight
                    to its end state
"""
import math
import os
import sys
import time

FRAME_MS = 16              # ~60 fps
SNAPPY = dict(stiffness=520.0, damping=34.0)     # settles in about a third of a second, ~3 % overshoot
GENTLE = dict(stiffness=140.0, damping=24.0)     # numbers and readings: no overshoot, about half a second
POP = dict(stiffness=700.0, damping=22.0)        # small things appearing: a visible bounce


class Spring:
    """A damped spring. value moves toward target; velocity is in units per second.

    stiffness pulls harder (faster), damping brakes (less overshoot). With damping^2 >= 4*stiffness*mass the
    spring never overshoots."""

    STEP = 1 / 240         # fixed physics step, so the motion is the same whatever the frame rate

    def __init__(self, value=0.0, stiffness=SNAPPY["stiffness"], damping=SNAPPY["damping"], mass=1.0,
                 rest_delta=0.002, rest_speed=0.02):
        self.value = self.target = float(value)
        self.velocity = 0.0
        self.k, self.c, self.m = float(stiffness), float(damping), float(mass)
        self.rest_delta, self.rest_speed = rest_delta, rest_speed

    def jump(self, value):
        """Put the spring straight at value, at rest."""
        self.value = self.target = float(value)
        self.velocity = 0.0

    def step(self, dt):
        """Advance dt seconds. Returns the new value."""
        dt = max(0.0, min(dt, 0.1))                    # a stalled frame must not fling the value away
        while dt > 1e-9:
            h = min(self.STEP, dt)
            a = (-self.k * (self.value - self.target) - self.c * self.velocity) / self.m
            self.velocity += a * h                     # semi-implicit Euler: stable for these springs
            self.value += self.velocity * h
            dt -= h
        if self.settled:
            self.value, self.velocity = self.target, 0.0
        return self.value

    @property
    def settled(self):
        scale = max(1.0, abs(self.target))
        return abs(self.value - self.target) < self.rest_delta * scale and abs(self.velocity) < self.rest_speed * scale

    @property
    def overshoots(self):
        return self.c * self.c < 4 * self.k * self.m


def animations_on():
    """Windows' Settings > Accessibility > Visual effects > Animation effects. True anywhere it can't be read."""
    if os.environ.get("CENTRALRGB_NO_ANIM"):
        return False
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        on = ctypes.c_int(1)
        if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(on), 0):   # SPI_GETCLIENTAREAANIMATION
            return bool(on.value)
    except Exception:
        pass
    return True


class Animator:
    """Drives one Spring on a Tk widget: on_frame(value) is called each frame until the spring settles.

        a = Animator(canvas, lambda v: canvas.coords(item, v, 0), **SNAPPY)
        a.to(120)            # glide there
        a.to(0, animate=False)   # jump
    """

    enabled = None         # cached animations_on(); tests and the app can set it

    def __init__(self, widget, on_frame, value=0.0, **spring):
        self.widget, self.on_frame = widget, on_frame
        self.spring = Spring(value, **spring)
        self._job, self._last = None, 0.0

    @property
    def value(self):
        return self.spring.value

    @property
    def running(self):
        return self._job is not None

    def to(self, target, animate=True):
        if Animator.enabled is None:
            Animator.enabled = animations_on()
        if not animate or not Animator.enabled:
            self.stop()
            self.spring.jump(target)
            self._frame()
            return
        self.spring.target = float(target)
        if self._job is None and not self.spring.settled:
            self._last = time.perf_counter()
            self._schedule()

    def stop(self):
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except Exception:
                pass
            self._job = None

    def _schedule(self):
        try:
            self._job = self.widget.after(FRAME_MS, self._tick)
        except Exception:                               # widget gone
            self._job = None

    def _frame(self):
        try:
            self.on_frame(self.spring.value)
        except Exception:                               # a drawing error must never take the app down
            pass

    def _tick(self):
        self._job = None
        try:
            if not self.widget.winfo_exists():
                return
        except Exception:
            return
        now = time.perf_counter()
        self.spring.step(now - self._last)
        self._last = now
        self._frame()
        if not self.spring.settled:
            self._schedule()


def ease_mix(a, b, t):
    """Linear mix of two numbers; t may go slightly past 0..1 while a spring overshoots."""
    return a + (b - a) * t


def lerp_slots(slots, s):
    """Position along a list of (x, width) slots at fractional index s, extrapolating a little past either end
    so an overshooting spring stretches past the last slot instead of stopping dead."""
    if not slots:
        return 0.0, 0.0
    if len(slots) == 1:
        return slots[0]
    i = int(math.floor(s))
    i = max(0, min(len(slots) - 2, i))
    f = s - i
    (x0, w0), (x1, w1) = slots[i], slots[i + 1]
    return x0 + (x1 - x0) * f, w0 + (w1 - w0) * f

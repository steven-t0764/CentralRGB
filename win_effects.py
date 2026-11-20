# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Windows window styling: dark (or light) title bar and (Windows 11) title bar colours that match the app, plus the
helpers that keep the window from flashing black while Tk draws (thaw, panel_background, cloak).
The glass and opacity helpers below are no longer used by the app. Safe no-ops on other systems / older Windows.

How the glass works with Tk: DWM blurs whatever is behind the window and the window's
pure-black (#000000) pixels become see-through, so the app paints its background black
and its panels in dark colours that read as tinted, frosted glass.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

IS_WIN = sys.platform == "win32"


def _hwnd(root) -> int:
    root.update_idletasks()
    return ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()


def win_build() -> int:
    try:
        return sys.getwindowsversion().build
    except Exception:
        return 0


def glass_supported() -> bool:
    return IS_WIN and win_build() >= 17134   # Windows 10 1803+


class _MARGINS(ctypes.Structure):
    _fields_ = [("l", ctypes.c_int), ("r", ctypes.c_int), ("t", ctypes.c_int), ("b", ctypes.c_int)]


class _ACCENT(ctypes.Structure):
    _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]


class _WCAD(ctypes.Structure):
    _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p), ("SizeOfData", ctypes.c_size_t)]


def _dwm_set(hwnd, attr, value: int):
    v = ctypes.c_int(value)
    return ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))


def dark_titlebar(root, dark: bool = True):
    """Dark title bar (or, with dark=False, the light one for the app's Light appearance)."""
    if not IS_WIN:
        return
    try:
        h = _hwnd(root)
        on = 1 if dark else 0
        if _dwm_set(h, 20, on) != 0:     # DWMWA_USE_IMMERSIVE_DARK_MODE
            _dwm_set(h, 19, on)          # older Win10 builds
        if win_build() >= 22000:
            _dwm_set(h, 33, 2)           # DWMWA_WINDOW_CORNER_PREFERENCE = round
    except Exception:
        pass


def titlebar_colors(root, caption_hex: str, border_hex: str, text_hex: str):
    """Windows 11: paint the title bar and window border to match the app (ignored on Windows 10)."""
    if not IS_WIN or win_build() < 22000:
        return
    try:
        h = _hwnd(root)
        def cref(hx):
            hx = hx.lstrip("#")
            r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
            return r | (g << 8) | (b << 16)            # COLORREF = 0x00BBGGRR
        _dwm_set(h, 35, cref(caption_hex))            # DWMWA_CAPTION_COLOR
        _dwm_set(h, 34, cref(border_hex))             # DWMWA_BORDER_COLOR
        _dwm_set(h, 36, cref(text_hex))               # DWMWA_TEXT_COLOR
    except Exception:
        pass


def apply_glass(root, tint_abgr: int = 0xB0100C0A) -> bool:
    """Turn on blur-behind. Returns True if applied."""
    if not glass_supported():
        return False
    try:
        h = _hwnd(root)
        dark_titlebar(root)
        m = _MARGINS(-1, -1, -1, -1)
        ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(wintypes.HWND(h), ctypes.byref(m))
        if win_build() >= 22621:         # Windows 11 22H2+: system acrylic backdrop
            if _dwm_set(h, 38, 3) == 0:  # DWMWA_SYSTEMBACKDROP_TYPE = DWMSBT_TRANSIENTWINDOW (acrylic)
                return True
        # Windows 10 / early 11: undocumented accent policy
        accent = _ACCENT(4, 2, tint_abgr, 0)          # ACCENT_ENABLE_ACRYLICBLURBEHIND
        data = _WCAD(19, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p), ctypes.sizeof(accent))
        fn = ctypes.windll.user32.SetWindowCompositionAttribute
        if not fn(wintypes.HWND(h), ctypes.byref(data)):
            accent.AccentState = 3                     # plain blur-behind fallback
            fn(wintypes.HWND(h), ctypes.byref(data))
        return True
    except Exception:
        return False


def set_opacity(root, pct: int):
    """Whole-window opacity, 60-100 %."""
    try:
        root.attributes("-alpha", max(0.6, min(1.0, pct / 100)))
    except Exception:
        pass


# ---- flicker-free page switching
WM_SETREDRAW = 0x000B
RDW_INVALIDATE, RDW_ERASE, RDW_ALLCHILDREN, RDW_UPDATENOW, RDW_FRAME = 0x1, 0x4, 0x80, 0x100, 0x400


def freeze(widget) -> int:
    """Stop Windows drawing a widget (and its children) until thaw(). Returns the handle to pass to thaw."""
    if sys.platform != "win32":
        return 0
    try:
        h = widget.winfo_id()
        ctypes.windll.user32.SendMessageW(wintypes.HWND(h), WM_SETREDRAW, 0, 0)
        return h
    except Exception:
        return 0


# What thaw asks Windows to do: mark everything for repainting and erase it first. The erase uses the window class
# brush, which panel_background() sets to the panel colour, so anything Tk has not drawn yet shows the panel colour,
# never black and never the old picture. (Leaving RDW_ERASE out kept the old page's pixels on screen wherever Tk
# didn't repaint.) No RDW_UPDATENOW: the caller does the drawing, all in one go, right after (App._paint_now).
THAW_FLAGS = RDW_INVALIDATE | RDW_ERASE | RDW_ALLCHILDREN | RDW_FRAME


def thaw(h: int):
    """Turn drawing back on and mark the whole area for repainting, cleared to the panel colour first."""
    if not h:
        return
    try:
        u = ctypes.windll.user32
        u.SendMessageW(wintypes.HWND(h), WM_SETREDRAW, 1, 0)
        u.RedrawWindow(wintypes.HWND(h), None, None, THAW_FLAGS)
    except Exception:
        pass


# ---- never show black while Tk is still drawing
# Fade-ins end at exactly 100 %. Stopping at 254/255 kept the window "layered" all the time, and a layered window
# smears when it scrolls (rows copied into repeated bands) and redraws more slowly. Coming back from the taskbar is
# covered by cloak() instead, and anything Windows clears before Tk draws shows the panel colour
# (panel_background). Kept as a name so older callers still work.
OPAQUE = 1.0

GCLP_HBRBACKGROUND = -10
_panel_brush = 0


def panel_background(root, hex_colour: str) -> bool:
    """Make Windows clear the app's windows to the panel colour instead of black whenever it clears them before
    Tk has drawn (the window class background brush). Returns True if it was set; does nothing off Windows."""
    global _panel_brush
    if not IS_WIN:
        return False
    try:
        u, g = ctypes.windll.user32, ctypes.windll.gdi32
        hx = hex_colour.lstrip("#")
        cref = int(hx[0:2], 16) | (int(hx[2:4], 16) << 8) | (int(hx[4:6], 16) << 16)
        g.CreateSolidBrush.restype = wintypes.HBRUSH
        brush = g.CreateSolidBrush(wintypes.COLORREF(cref))
        if not brush:
            return False
        setter = getattr(u, "SetClassLongPtrW", None) or u.SetClassLongW     # 32-bit Python has only the latter
        setter.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        setter.restype = ctypes.c_size_t
        inner = root.winfo_id()                       # Tk's own window class (every widget shares it)
        for h in {_hwnd(root), inner}:                # and the outer window with the title bar
            setter(wintypes.HWND(h), GCLP_HBRBACKGROUND, brush)
        old, _panel_brush = _panel_brush, brush
        if old:
            g.DeleteObject(wintypes.HGDIOBJ(old))     # the previous theme's brush
        return True
    except Exception:
        return False


# ---- hide the window from the screen while it is being drawn (Windows 8+)
DWMWA_CLOAK = 13


def cloak(root, on: bool) -> bool:
    """Hide (on=True) or show the window on screen while it stays open and can still be drawn (DWM cloaking).
    Used for a moment while the window comes back from the taskbar, so it only appears once it is fully drawn.
    Returns True if it worked; does nothing off Windows or on Windows 7."""
    if not IS_WIN or win_build() < 9200:
        return False
    try:
        return _dwm_set(_hwnd(root), DWMWA_CLOAK, 1 if on else 0) == 0
    except Exception:
        return False


def dwm_flush():
    """Wait until Windows has put the latest drawing on screen (at most one screen refresh)."""
    if not IS_WIN:
        return
    try:
        ctypes.windll.dwmapi.DwmFlush()
    except Exception:
        pass

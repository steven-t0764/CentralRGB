# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Windows window effects: frosted-glass (acrylic) blur behind the window, dark title bar,
and whole-window opacity. Safe no-ops on other systems / older Windows.

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


def dark_titlebar(root):
    if not IS_WIN:
        return
    try:
        h = _hwnd(root)
        if _dwm_set(h, 20, 1) != 0:      # DWMWA_USE_IMMERSIVE_DARK_MODE
            _dwm_set(h, 19, 1)           # older Win10 builds
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

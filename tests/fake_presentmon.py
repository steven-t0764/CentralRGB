# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fake PresentMon output: CSV lines shaped like the real tool's, for the FPS overlay tests.

PresentMon 1.x names the frame-time column MsBetweenPresents; 2.x uses FrameTime and adds more columns.
Both layouts are here, plus the error text PresentMon prints when it can't start."""

V1_HEADER = ("Application,ProcessID,SwapChainAddress,Runtime,SyncInterval,PresentFlags,AllowsTearing,PresentMode,"
             "TimeInSeconds,MsInPresentAPI,MsBetweenPresents,MsBetweenDisplayChange,MsUntilRenderComplete")
V2_HEADER = ("Application,ProcessID,SwapChainAddress,PresentRuntime,SyncInterval,PresentFlags,AllowsTearing,"
             "PresentMode,FrameType,CPUStartTime,FrameTime,CPUBusy,CPUWait,DisplayLatency,DisplayedTime")

ACCESS_DENIED = ("error: failed to start trace session: access denied.\n"
                 "PresentMon requires either administrative privileges or to be run by a user in the\n"
                 "Performance Log Users user group. View the readme for more details.")
TOO_MANY = "error: failed to start trace session (error=1450): too many sessions running."


def v1_row(app, pid, ms, chain="0x1A2B", mode="Hardware: Independent Flip"):
    return f"{app},{pid},{chain},DXGI,0,0,1,{mode},12.5,0.1,{ms:.3f},{ms:.3f},0.5"


def v2_row(app, pid, ms, chain="0x1A2B", mode="Hardware Composed: Independent Flip"):
    return f"{app},{pid},{chain},DXGI,0,0,1,{mode},Application,1234.5,{ms:.3f},{ms * 0.8:.3f},{ms * 0.2:.3f},9.1,{ms:.3f}"


def stream(header, rows, preamble=()):
    """An iterable of lines like PresentMon's stdout (each ends in a newline)."""
    return [ln + "\n" for ln in (*preamble, header, *rows)]


def game(app, pid, fps, frames, v=2, **kw):
    row = v2_row if v == 2 else v1_row
    return [row(app, pid, 1000.0 / fps, **kw) for _ in range(frames)]

# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Preview Central RGB on a simulated copy of the user's PC: MSI B550-A PRO, Razer Huntsman V2 TKL and four
Corsair Vengeance RGB DDR4 sticks and a SteelSeries mouse, with MSI Center / Mystic Light and SteelSeries GG
"running".

    xvfb-run -a -s "-screen 0 1300x840x24" python3 tests/preview_user_pc.py [out] [--ram-visible] [--mouse-visible]
                                                                            [--ddr5] [--vengeance-pro]
                                                                            [preview.py options]

By default the RAM and the mouse are hidden, as when MSI Center holds the SMBus and SteelSeries GG the mouse,
so the Devices page shows what it tells the user. --ddr5 swaps in a DDR5 PC instead (Intel Z790, two Kingston
FURY Beast RGB DDR5 sticks, fake_openrgb.Z790_DDR5_PC) with the DDR5 RAM guard on. --vengeance-pro is the
user's PC as of 2026-11-20 (fake_openrgb.B550_PRO_PC): four Vengeance RGB PRO sticks (CMW32GX4M2D3600C18,
reported by Windows with the maker "Unknown") and only SteelSeries GG / Engine running. Everything else is
tests/preview.py.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import fake_openrgb  # noqa: E402
import rgb_engine as eng  # noqa: E402

ram_visible = "--ram-visible" in sys.argv
mouse_visible = "--mouse-visible" in sys.argv
ddr5 = "--ddr5" in sys.argv
vpro = "--vengeance-pro" in sys.argv      # the owner's PC as of 2026-11-20: 4x Vengeance RGB PRO (CMW...)
sys.argv = [a for a in sys.argv if a not in ("--ram-visible", "--mouse-visible", "--ddr5", "--vengeance-pro")]
os.environ["CENTRALRGB_FAKE_DDR5"] = "1" if ddr5 else "0"

_install = fake_openrgb.install
PC = fake_openrgb.Z790_DDR5_PC if ddr5 else fake_openrgb.B550_PRO_PC if vpro else fake_openrgb.B550_PC
WMI = (fake_openrgb.KINGSTON_FURY_DDR5_WMI if ddr5 else fake_openrgb.CORSAIR_VENGEANCE_PRO_DDR4_WMI if vpro
       else fake_openrgb.CORSAIR_VENGEANCE_DDR4_WMI)
fake_openrgb.install = lambda e=None, **k: _install(e, devices=PC,
                                                    ram_blocked=not ram_visible, mouse_blocked=not mouse_visible)
_check = eng.system_check


def _inventory():
    """What Windows would report on that PC."""
    eng.RAM_INVENTORY[:] = list(WMI)
    eng.MOUSE_INVENTORY[:] = fake_openrgb.STEELSERIES_MOUSE_WMI + fake_openrgb.RAZER_KEYBOARD_POINTER_WMI
    eng.KEYBOARD_INVENTORY[:] = list(fake_openrgb.RAZER_KEYBOARD_WMI)


def _system_check():
    rows = _check()
    _inventory()
    if vpro:                              # the rows Windows gives on that PC (the RAM line as the app now names it)
        rows += [("ok", "Running as administrator."), ("ok", "PawnIO driver found (needed for RAM / older motherboards)."),
                 ("warn", "Other RGB software is running and may fight for control: SteelSeries Engine, SteelSeries GG. "
                          "Close it (and disable it at startup)."),
                 ("info", "Motherboard: Micro-Star International Co., Ltd. B550-A PRO (MS-7C56)"),
                 ("info", f"RAM sticks: {len(WMI)} ({eng.ram_summary(WMI)})")]
    return rows


eng.system_check = _system_check
_inventory()
eng.find_conflicts = ((lambda: {"SteelSeries GG": [4343], "SteelSeries Engine": [4344]}) if vpro else
                      (lambda: {"MSI Center / Mystic Light": [4242], "SteelSeries GG": [4343]}))
eng.is_admin = lambda: True
eng.pawnio_installed = lambda: True

import preview  # noqa: E402

preview.main()

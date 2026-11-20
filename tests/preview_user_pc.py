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
                                                                            [preview.py options]

By default the RAM and the mouse are hidden, as when MSI Center holds the SMBus and SteelSeries GG the mouse,
so the Devices page shows what it tells the user. Everything else is tests/preview.py.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import fake_openrgb  # noqa: E402
import rgb_engine as eng  # noqa: E402

ram_visible = "--ram-visible" in sys.argv
mouse_visible = "--mouse-visible" in sys.argv
sys.argv = [a for a in sys.argv if a not in ("--ram-visible", "--mouse-visible")]

_install = fake_openrgb.install
fake_openrgb.install = lambda e=None, **k: _install(e, devices=fake_openrgb.B550_PC, ram_blocked=not ram_visible,
                                                    mouse_blocked=not mouse_visible)
_check = eng.system_check


def _inventory():
    """What Windows would report on that PC."""
    eng.RAM_INVENTORY[:] = list(fake_openrgb.CORSAIR_VENGEANCE_DDR4_WMI)
    eng.MOUSE_INVENTORY[:] = fake_openrgb.STEELSERIES_MOUSE_WMI + fake_openrgb.RAZER_KEYBOARD_POINTER_WMI
    eng.KEYBOARD_INVENTORY[:] = list(fake_openrgb.RAZER_KEYBOARD_WMI)


def _system_check():
    rows = _check()
    _inventory()
    return rows


eng.system_check = _system_check
_inventory()
eng.find_conflicts = lambda: {"MSI Center / Mystic Light": [4242], "SteelSeries GG": [4343]}
eng.is_admin = lambda: True
eng.pawnio_installed = lambda: True

import preview  # noqa: E402

preview.main()

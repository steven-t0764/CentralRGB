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
Corsair Vengeance RGB DDR4 sticks, with MSI Center / Mystic Light and SteelSeries GG "running".

    xvfb-run -a -s "-screen 0 1300x840x24" python3 tests/preview_user_pc.py [out] [--ram-visible] [preview.py options]

By default the RAM is hidden, as when another app holds the SMBus. Everything else is tests/preview.py.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]

import fake_openrgb  # noqa: E402
import rgb_engine as eng  # noqa: E402

ram_visible = "--ram-visible" in sys.argv
if ram_visible:
    sys.argv.remove("--ram-visible")

_install = fake_openrgb.install
fake_openrgb.install = lambda e=None, **k: _install(e, devices=fake_openrgb.B550_PC, ram_blocked=not ram_visible)
_check = eng.system_check


def _system_check():
    rows = _check()
    eng.RAM_INVENTORY[:] = list(getattr(fake_openrgb, "CORSAIR_VENGEANCE_DDR4_WMI", []))
    return rows


eng.system_check = _system_check
eng.RAM_INVENTORY[:] = list(getattr(fake_openrgb, "CORSAIR_VENGEANCE_DDR4_WMI", []))
eng.find_conflicts = lambda: {"MSI Center / Mystic Light": [4242], "SteelSeries GG": [4343]}
eng.is_admin = lambda: True
eng.pawnio_installed = lambda: True

import preview  # noqa: E402

preview.main()

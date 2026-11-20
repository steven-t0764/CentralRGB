# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""When the nightly workflow publishes a release (tools/auto_release.py): batches small tweaks, cuts on 3+ changes,
a big change or an explicit version bump, and picks the next version."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import auto_release as ar  # noqa: E402


class AutoRelease(unittest.TestCase):
    def test_latest_tag_uses_version_order(self):
        self.assertEqual(ar.latest_tag(["v2.2.1", "v2.10", "v2.3.2", "test-ddr5-build", "v2.9.9"]), "v2.10")

    def test_entries_from_diff(self):
        diff = "+++ b/CHANGELOG.md\n+- **A:** one\n- **old** line\n+## 2.5.0\n+- **B:** two <!-- big -->\n"
        self.assertEqual(ar.added_entries(diff), ["- **A:** one", "- **B:** two <!-- big -->"])

    def test_small_tweaks_wait(self):
        self.assertEqual(ar.decide("v2.4.0", "2.4.0", ["- a", "- b"])[0], False)
        self.assertEqual(ar.decide("v2.4.0", "2.4.0", [])[0], False)

    def test_three_changes_cut_a_patch(self):
        self.assertEqual(ar.decide("v2.4.0", "2.4.0", ["- a", "- b", "- c"])[:2], (True, "2.4.1"))

    def test_feature_bumps_minor(self):
        self.assertEqual(ar.decide("v2.4.3", "2.4.0", ["- a <!-- feature -->", "- b", "- c"])[:2], (True, "2.5.0"))

    def test_one_big_change_is_enough(self):
        self.assertEqual(ar.decide("v2.4.0", "2.4.0", ["- huge <!-- big -->"])[:2], (True, "2.5.0"))

    def test_explicit_version_bump_wins(self):
        self.assertEqual(ar.decide("v2.3.2", "2.4.0", ["- a"])[:2], (True, "2.4.0"))

    def test_force(self):
        self.assertEqual(ar.decide("v2.4.0", "2.4.0", ["- a"], force=True)[:2], (True, "2.4.1"))

    def test_notes_drop_markers(self):
        n = ar.notes("2.5.0", ["- **X:** new thing <!-- big -->"])
        self.assertIn("- **X:** new thing", n)
        self.assertNotIn("<!--", n)


if __name__ == "__main__":
    unittest.main()

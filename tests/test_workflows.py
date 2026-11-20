# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without
# even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with this program. If not,
# see <https://www.gnu.org/licenses/>.
"""Every merge commit on main must get the windows check.

auto-merge.yml merges with GITHUB_TOKEN, which does not fire push workflows, so it has to start the
main build itself. These checks read the workflow files as text (no YAML library needed)."""
import pathlib
import re
import unittest

WF = pathlib.Path(__file__).resolve().parent.parent / ".github" / "workflows"


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.build = (WF / "build.yml").read_text(encoding="utf-8")
        self.merge = (WF / "auto-merge.yml").read_text(encoding="utf-8")

    def test_build_can_be_dispatched_and_has_windows_job(self):
        self.assertRegex(self.build, r"(?m)^\s+workflow_dispatch:")
        self.assertRegex(self.build, r"(?m)^  windows:")
        self.assertRegex(self.build, r"(?ms)^  push:\s*\n\s+branches: \[main")

    def test_auto_merge_dispatches_main_build_after_merging(self):
        merge_at = self.merge.find("gh pr merge")
        run_at = self.merge.find("gh workflow run build.yml")
        self.assertGreater(merge_at, 0)
        self.assertGreater(run_at, merge_at, "the main build must be started after the merge")
        self.assertIn("--ref main", self.merge[run_at:].splitlines()[0])
        self.assertRegex(self.merge, r"(?m)^\s+actions: write")

    def test_auto_merge_still_only_merges_passing_tested_commits(self):
        self.assertIn("conclusion == 'success'", self.merge)
        self.assertIn("headRefOid == $ENV.SHA", self.merge)
        self.assertIn('index("do-not-merge")', self.merge)
        self.assertIsNotNone(re.search(r"isDraft \| not", self.merge))

    def test_merges_run_one_at_a_time(self):
        self.assertRegex(self.merge, r"(?m)^concurrency:")
        self.assertRegex(self.merge, r"cancel-in-progress: false")


if __name__ == "__main__":
    unittest.main()

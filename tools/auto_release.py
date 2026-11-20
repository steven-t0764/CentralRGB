# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Decides whether enough has changed since the last release to publish a new one, and writes its notes.
Run by .github/workflows/release.yml every night (and on demand). No commits are made: the version comes from the
tag, and the build stamps it into the app.

A release is cut when, since the last vX.Y.Z tag, any of these is true:
  * APP_VERSION in rgb_engine.py was bumped above the last tag (an explicit release, e.g. "Version 2.4.0"),
  * at least MIN_CHANGES user-visible changelog entries were added (one "- " line each in CHANGELOG.md),
  * an added entry is marked <!-- big -->,
  * it was started by hand with "force".
Small tweaks pile up until one of these holds. The new version is APP_VERSION when it was bumped; otherwise the
minor number goes up when an entry is marked <!-- big --> or <!-- feature -->, and the patch number otherwise.

    python tools/auto_release.py [--force]    # prints release=, tag=, version= lines and writes release-notes.md
"""
import os
import re
import subprocess
import sys
from pathlib import Path

MIN_CHANGES = 3
ROOT = Path(__file__).resolve().parent.parent
TAG_RE = re.compile(r"^v(\d+)\.(\d+)(?:\.(\d+))?$")
MARK_RE = re.compile(r"\s*<!--\s*(big|feature)\s*-->\s*", re.I)


def parse_version(s):
    m = TAG_RE.match(s if s.startswith("v") else "v" + s)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else None


def fmt(v):
    return f"{v[0]}.{v[1]}.{v[2]}"


def latest_tag(tags):
    vs = [(parse_version(t), t) for t in tags if parse_version(t)]
    return max(vs)[1] if vs else None


def added_entries(diff_text):
    """Changelog entries ('- ...' lines) added in a unified diff of CHANGELOG.md."""
    out = []
    for line in diff_text.splitlines():
        if line.startswith("+- ") and not line.startswith("+++"):
            out.append(line[1:].rstrip())
    return out


def decide(last_tag, app_version, entries, force=False, min_changes=MIN_CHANGES):
    """Returns (release?, version string, reason)."""
    last = parse_version(last_tag) if last_tag else (0, 0, 0)
    app = parse_version(app_version) if app_version else None
    big = any(re.search(r"<!--\s*big\s*-->", e, re.I) for e in entries)
    feature = big or any(re.search(r"<!--\s*feature\s*-->", e, re.I) for e in entries)
    if app and app > last:
        return True, fmt(app), f"APP_VERSION was bumped to {fmt(app)}"
    if not entries and not force:
        return False, None, "nothing new since the last release"
    if not (force or big or len(entries) >= min_changes):
        return False, None, f"only {len(entries)} change(s) since {last_tag}; waiting for {min_changes} or a big one"
    nxt = (last[0], last[1] + 1, 0) if feature else (last[0], last[1], last[2] + 1)
    why = "started by hand" if force else ("a big change" if big else f"{len(entries)} changes")
    return True, fmt(nxt), why


def notes(version, entries):
    lines = [f"## What's new in Central RGB {version}", ""]
    lines += [MARK_RE.sub(" ", e).rstrip() for e in entries] or ["- Maintenance release."]
    lines += ["", "Download **CentralRGB-Setup.exe** (recommended) or the portable **Central.RGB.exe**. "
              "Already on 2.4 or newer? Central RGB offers this update itself (**Settings → Updates**). "
              "Checksums are in **SHA256SUMS.txt**."]
    return "\n".join(lines) + "\n"


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def main(argv):
    force = "--force" in argv or os.environ.get("FORCE_RELEASE", "").lower() == "true"
    last = latest_tag(git("tag", "--list", "v*").split())
    m = re.search(r'^APP_VERSION = "([^"]+)"', (ROOT / "rgb_engine.py").read_text(encoding="utf-8"), re.M)
    if last and git("rev-list", "-n", "1", last).strip() == git("rev-parse", "HEAD").strip():
        release, version, why = False, None, f"{last} is already the newest commit"
        entries = []
    else:
        diff = git("diff", f"{last}..HEAD", "--", "CHANGELOG.md") if last else ""
        entries = added_entries(diff)
        release, version, why = decide(last, m.group(1) if m else None, entries, force)
    print(f"last={last or ''}\nrelease={'true' if release else 'false'}\nversion={version or ''}\n"
          f"tag={'v' + version if version else ''}\nreason={why}")
    if release:
        (ROOT / "release-notes.md").write_text(notes(version, entries), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# Review of the status report (docs/vizor-report.md, PR #38)

Reviewed on 2026-11-20 against `main` at `33a8f80` (the squash merge of PR #38, head `c9c3a58`). Issue #37.
Read-only: no product code was changed. Every link in the report was checked against the merged PRs, the merge
commits and the review reports it points to.

## Verdict: needs changes

The report is short, every link opens the right thing, and the merge itself is clean. But three of its lines are
wrong:

- It says the Light mode polish (PR #35) has no review. It does, and the verdict is **ready**.
- It lists two items under **Works now** whose reviews say **needs changes** and name defects: RAM and mouse
  detection (PR #23), and the black-flash fix (PR #29).

This is a defect in the report, not in the app. A small follow-up task can fix it by editing only
`docs/vizor-report.md`. The fixes are below.

## What I checked

| Check | Result |
| --- | --- |
| `xvfb-run -a python -m unittest discover tests` on `33a8f80` (Python 3.12 venv, `requirements.txt` minus pythonnet, Pillow with ImageTk, python3-tk) | **150 tests, OK** (0 failures, 0 errors) |
| Every link target exists | Yes. Merge commits `316c63e`, `35d3528`, `5730f6a`, `e10d3f8` and the follow-up `c614d9f` are on `main`. The review commits `62950e2` (test-run.md), `e2852c4` (review-device-detection.md), `4135f28` (review-ddr5-lighting.md), `768a965` (review-repaint.md) and `d5c040c` (review-theme-toggle.md) all exist on pushed review branches and contain the linked file. `docs/review-bugfixes.md` and `docs/review-updater.md` are on `main`. PRs #18, #20, #23, #26, #29, #34 and #35 are the PRs the report names. |
| Fan safety rules | Unchanged. PR #38 changes only `CHANGELOG.md` and `docs/vizor-report.md`. `tests/test_fan_safety.py` passes. |
| DDR5 once-per-boot guard | Unchanged (no code in the diff). `tests/test_ddr5_guard.py` passes. |
| GPL-3.0 headers | No source file was added or changed, so nothing needs one. The existing headers are untouched. |
| Restyling outside the task | None. The PR has no code or UI changes. |
| CHANGELOG / README / tests README | `CHANGELOG.md` has a new line under `## Unreleased` that points to the report. No behaviour, setting, page or test changed, so `README.md` and `tests/README.md` correctly stay as they are. |
| Claude/Anthropic lines | None in the commit `c9c3a58`, the squash commit `33a8f80` or the PR #38 description. |

## Findings

1. **docs/vizor-report.md, last line ("Light mode polish not reviewed yet"). False.**
   PR #35 was reviewed: the second pass in `docs/review-theme-toggle.md` at `d5c040c` says **"Verdict: ready. All
   three findings are fixed."** The PR #38 description repeats the same mistake ("has no review report yet").
   **Fix:** delete this line from "Still not working". Change the "Light mode polish" line under Works now to link
   the review: `[review: ready](https://github.com/steven-t0764/CentralRGB/blob/d5c040c/docs/review-theme-toggle.md)`.

2. **docs/vizor-report.md, Works now, "RAM and mouse detection". Listed as working although its review says
   needs changes.** The review at `e2852c4` gives the verdict **needs changes**, and finding 1 is a defect: false
   "Mouse not detected" warnings. No later PR fixes it. The report lists the same defect under "Still not working",
   so it contradicts itself.
   **Fix:** narrow the line to what the review found sound: "**RAM detection and Close them:** names the blocker
   (MSI Center, SteelSeries GG), Close them stops all MSI Center services and re-detects once. Mouse check: see
   below." Link it as `review: needs changes (mouse)`.

3. **docs/vizor-report.md, Works now, "Black flashes". Listed as working although its review says needs changes
   and the fix is unproven.** The review at `768a965` gives the verdict **needs changes**:
   - Finding 2 is a likely defect: the panel brush reaches the FPS overlay.
   - Finding 3 says the simulated frame check also passes on the *old* code, so "no black window in the simulated
     frames" doesn't show anything is fixed.

   The report's own "Still not working" section says the same thing.
   **Fix:** move this item to "Still not working or not proven", for example: "**Black flashes:** fix merged (PR
   #29), but not shown to work. The simulated check also passes on the old code. Needs `tests/restore_check.py` on
   the real PC." Then remove the duplicate "Black flash on the real PC unproven" line, or merge the two lines.

4. **docs/vizor-report.md, "RAM flicker (bug 3)". The review verdict is left out.** `docs/review-bugfixes.md`
   gives `fix-ram-flicker` the verdict **needs changes** (two fixes). The follow-up `c614d9f` makes both fixes. I
   checked the diff: the log line now says the Devices page, and `ram_cycle = max(ram_every, n_ram)` gives each
   stick its own tick. Nobody has reviewed the follow-up, though. The line's plain "[review]" link reads as an
   approval.
   **Fix:** label the link "review: needs changes, both fixed in `c614d9f` (not re-reviewed)".

5. **docs/vizor-report.md, "Test run". The evidence is for an old main.** The linked `docs/test-run.md` covers
   `main` at `3c50514`: 54 tests, before bugs 2-5 reached main and before PRs #18–#35. The line says "all tests pass
   on main", which is true today (150 tests OK at `33a8f80`, run for this review). The linked file doesn't show
   that.
   **Fix:** reword the line to "150 tests pass on main at `33a8f80`; the Windows build is green (PR #38 run)". Link
   the PR #38 `windows` run (https://github.com/steven-t0764/CentralRGB/actions/runs/44708285403/job/136193242390),
   and keep `test-run.md` as the earlier baseline.

6. **docs/vizor-report.md, links to `blob/main/...` (5 × `review-bugfixes.md`, 1 × `review-updater.md`). Not
   pinned.** These links will show whatever is on `main` later, unlike the other review links, which are pinned to
   a commit.
   **Fix:** replace `blob/main/` with `blob/33a8f80/` in those six links.

7. **docs/vizor-report.md, "DDR5 RGB RAM: every effect works". Overstated (nit).** The review at `4135f28` shows
   the effects only in tests (`test_ddr5_lighting.Effects`) on fake hardware. The report already says real DDR5
   hasn't been tried.
   **Fix:** "every effect works in the tests on simulated DDR5".

8. **Not in the report: Claude footers still in two merged PR descriptions (process, not app).** PR #29 and PR #35
   both still end with `_Generated by [Claude Code](https://claude.ai/code)_`. CLAUDE.md forbids this, and the
   reviews at `768a965` (finding 1) and `d5c040c` flagged it. PR #18 had the same footer (review-updater.md).
   **Fix:** the owner edits that line out of those PR descriptions. Optionally, add a "Still open" line for it.

## Notes (no change needed)

- The squash commit `33a8f80` shows the author name `lilsteve01` (GitHub's account display name) with the
  owner's noreply email. The branch commit `c9c3a58` uses `steven-t0764`. Both have the right identity, and
  neither has an attribution line.
- The review links point at commits that only live on review branches (`review-*`, `test-run-report`). If those
  branches are deleted, the links can stop working. Merging the review reports to `main` would make them
  permanent.
- The "Still not working" lines on the mouse (findings 1-2), the FPS overlay (finding 2), the real-PC RAM and FPS
  checks, and real DDR5 all match their reviews.

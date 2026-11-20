# Test run on main

Run on 2026-11-20 for issue #14 (plan `bugfix-1`, phase `test-run`).

**Verdict: all 54 tests pass on the latest main, and its Windows build check is green.**

## What was tested

- `main` at commit [`3c50514`](https://github.com/steven-t0764/CentralRGB/commit/3c50514debf471e1344f4b101896621c73d4d8f5)
  ("Merge pull request #13 from steven-t0764/plan-updater").
- No source file was changed for this run.

## Compile check

`python -m py_compile` on every `.py` file in the repo root and `tests/`: **23 files, 0 errors**.

## Test suite

Command: `xvfb-run -a python3.12 -m unittest discover tests -v`, on Linux under Xvfb, Python 3.12.3,
with the packages from `requirements.txt` installed (customtkinter 6.0.0, openrgb-python 0.3.8, psutil 7.2.2,
pystray 0.19.5, pythonnet 3.2.1) and Pillow 10.2.0 with ImageTk.

| Ran | Passed | Failed | Errors | Skipped |
| --- | --- | --- | --- | --- |
| 54 | 54 | 0 | 0 | 0 |

Result line: `Ran 54 tests in 16.490s` / `OK`.

### Failing tests

None.

### Setup notes (not app bugs)

The first attempts in this container failed for environment reasons only, and were fixed by installing packages,
not by changing code:

1. Before `requirements.txt` was installed: 5 modules could not import `openrgb` / `psutil` (5 errors, 5 skipped).
2. The default Python 3.11 here has no `tkinter`, so the run moved to Python 3.12 (the version CI uses).
3. The system Pillow had no `ImageTk`, so `test_page_switch` failed and 7 tests skipped with
   "central_rgb could not be imported". Installing `python3-pil.imagetk` fixed both.

Anyone running the suite on a bare Linux box needs `python3-tk` and a Pillow with `ImageTk` as well as `requirements.txt`.

## Windows check (`windows` job of the Build Central RGB workflow)

- **Most recent run on `main`: success.** Run #88 on push of `91446df` (2026-11-19):
  https://github.com/steven-t0764/CentralRGB/actions/runs/44566880991/job/135710956555
  (tests, installed-folder build, portable exe, self-test and installer all passed).
- No `windows` run exists for the push of `3c50514` itself: the merges of PR #12 and PR #13 did not start a push run
  on `main`. The commits after `91446df` change only `.github/vizor-plan.json` and `CLAUDE.md`, so no code, test,
  dependency or workflow file differs from what run #88 tested.
- The same tree was checked by PR #13's run: run #93 on `1727c43`, whose tree is identical to `3c50514`:
  **success**, https://github.com/steven-t0764/CentralRGB/actions/runs/44678664765/job/136096514075

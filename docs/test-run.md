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

## Review

Independent check for issue #15, by Fabian, 2026-11-20.

**Verdict: confirmed.** The report matches a fresh re-run, and both Windows links are what the report says they are.

- **Same commit.** The branch is based on the latest `main`, `3c50514`, and the suite was re-run on a detached checkout of `3c50514`.
- **Same counts.** `xvfb-run -a python3.12 -m unittest discover tests -v` (Python 3.12, `requirements.txt` plus `python3-tk`
  and `python3-pil.imagetk`): `Ran 54 tests in 16.813s` / `OK`. 54 passed, 0 failed, 0 errors, 0 skipped. No failing tests.
- **Fan safety ran and passed.** All 6 tests in `tests/test_fan_safety.py` ran and passed: `test_auto_leaves_fans_to_bios`,
  `test_emergency_cpu`, `test_emergency_gpu_overrides_manual`, `test_floors`, `test_manual_below_floor_is_raised` and
  `test_stop_hands_fans_back`.
- **Windows links.** Job `135710956555` is the `windows` job of run #88, a push on `main` at `91446df`, with conclusion
  success. Job `136096514075` is the `windows` job of run #93 on `plan-updater` at `1727c43`, with conclusion success.
  Neither link points at `3c50514` itself. The run list for `main` confirms that no Build Central RGB run exists for `3c50514`,
  so this is the closest evidence there is, and the report says so openly. I confirmed that `1727c43` and `3c50514` have the
  same tree (`df173bf`) and that `91446df..3c50514` changes only `.github/vizor-plan.json` and `CLAUDE.md`, so the green
  `windows` runs cover exactly the code on `main`.
- **Branch scope.** `main...test-run-report` changes only `docs/test-run.md`. The commit author is `steven-t0764`, and the
  commit has no Co-Authored-By, Claude-Session or Claude/Anthropic attribution line. The file's only mention of
  `CLAUDE.md` is the name of a changed file, not an attribution.
- One small extra environment note: on a bare Linux box, importing `pystray` directly fails without the GTK typelibs. The
  test suite does not need them and is unaffected.

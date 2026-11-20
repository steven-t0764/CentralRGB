# Central RGB: rules for every agent run

These apply to every Claude/Vizor worker in this repo, on every task, without being asked.

## Ship through checks, not by hand
- Work on a branch and open a pull request into `main`. Never push straight to `main`.
- `main` only takes a PR once the **`windows`** check passes (tests + Windows build + self-test). A passing PR merges itself; that is the approval.
- If `windows` fails, read the log, fix it on the same branch and push again. Don't finish a task with a red check.
- Use a draft PR or the `do-not-merge` label only when a human decision is truly needed.

## Every change ships with its tests and docs
- Add or update tests in `tests/` for the behaviour you changed (new fakes, harnesses and preview scripts go there too, with a line in `tests/README.md`).
- Before pushing: `python -m py_compile` every changed `.py`, then `python -m unittest discover tests` (use `xvfb-run -a` on Linux). Both must pass.
- Update the docs in the **same PR**: add a line under `## Unreleased` in `CHANGELOG.md` (plain English, what the user notices), and update `README.md` / `CONTRIBUTING.md` / `tests/README.md` wherever behaviour, settings or pages changed.
- Visual changes: run `tests/preview.py` (or `tests/preview_user_pc.py`) under Xvfb, look at the screenshots, and link them or describe them in the PR.

## Rules that must not break
- Fan safety: fans never below 20 %, pumps never below 70 %, every fan to 100 % at 90 °C CPU or GPU, closing the app hands fans back to the BIOS. `tests/test_fan_safety.py` must keep passing.
- The DDR5 once-per-boot RAM guard (on the `test-ddr5` branch) stays exactly as it is.
- GPL-3.0 header on every source file. Windows-only code fails quietly elsewhere. Settings stay readable from older versions.
- Don't restyle anything outside the task.

## Identity
- Commit as the owner: `git -c user.name="steven-t0764" -c user.email="323795143+steven-t0764@users.noreply.github.com" commit ...`
- No `Co-Authored-By`, `Claude-Session`, "Generated with Claude Code" or any Claude/Anthropic line in commits, PR descriptions or issue comments.

## Getting unstuck before calling it blocked
- Don't stop for small questions or minor issues: pick the sensible option, say which in the PR or result, and keep going.
- Try at least two different approaches, and check the other agents' open branches, PRs and issues for the same problem or a fix you can reuse.
- If a check fails because of someone else's change, fix it in your PR or say exactly which commit broke it.
- Report blocked (vizor-blocked) only for missing credentials, spending, an outside commitment, or a real product decision. Say what you tried and propose the next step, so the investigator can route it to another agent.

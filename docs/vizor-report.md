# Central RGB: what works and what doesn't

Short status after plan `bugfix-1` (2026-11-20). Checked on Linux with simulated hardware and on the Windows build
check. Nothing here was tried on Steven's own PC.

## Works now

- **RAM not detected (bug 2):** the Devices page names the program holding the RAM and retries once after Close them. [Merge `316c63e`](https://github.com/steven-t0764/CentralRGB/commit/316c63e), [review: ready](https://github.com/steven-t0764/CentralRGB/blob/main/docs/review-bugfixes.md)
- **RAM flicker (bug 3):** steady lower RAM rate, one stick per tick, unchanged frames skipped. [Merge `35d3528`](https://github.com/steven-t0764/CentralRGB/commit/35d3528) + follow-up [`c614d9f`](https://github.com/steven-t0764/CentralRGB/commit/c614d9f), [review](https://github.com/steven-t0764/CentralRGB/blob/main/docs/review-bugfixes.md)
- **FPS counter (bug 4):** PresentMon restarts itself, launchers and anti-cheat helpers are ignored, and it says why when it can't count. [Merge `5730f6a`](https://github.com/steven-t0764/CentralRGB/commit/5730f6a), [review: ready](https://github.com/steven-t0764/CentralRGB/blob/main/docs/review-bugfixes.md)
- **Restore and page-switch glitches (bug 5):** fast page clicks no longer leave a half-built page. [Merge `e10d3f8`](https://github.com/steven-t0764/CentralRGB/commit/e10d3f8), [review: ready](https://github.com/steven-t0764/CentralRGB/blob/main/docs/review-bugfixes.md)
- **Test run:** all tests pass on main, and the Windows build is green. [docs/test-run.md](https://github.com/steven-t0764/CentralRGB/blob/62950e2/docs/test-run.md) (confirmed by Fabian)
- **One-click updates:** checks, verifies SHA-256, installs and reopens. A stuck "Downloading..." was fixed. [PR #18](https://github.com/steven-t0764/CentralRGB/pull/18), [PR #20](https://github.com/steven-t0764/CentralRGB/pull/20), [review](https://github.com/steven-t0764/CentralRGB/blob/main/docs/review-updater.md)
- **RAM and mouse detection:** names the blocker (MSI Center, SteelSeries GG), Close them stops all MSI Center services and re-detects once. [PR #23](https://github.com/steven-t0764/CentralRGB/pull/23), [review](https://github.com/steven-t0764/CentralRGB/blob/e2852c4/docs/review-device-detection.md)
- **DDR5 RGB RAM:** kits recognised, every effect works, once-per-boot guard kept as it was. [PR #26](https://github.com/steven-t0764/CentralRGB/pull/26), [review: ready](https://github.com/steven-t0764/CentralRGB/blob/4135f28/docs/review-ddr5-lighting.md)
- **Black flashes:** no black window or black boxes on restore or section switch in the simulated frames. [PR #29](https://github.com/steven-t0764/CentralRGB/pull/29), [review](https://github.com/steven-t0764/CentralRGB/blob/768a965/docs/review-repaint.md)
- **Dark / Light toggle:** in Settings → Appearance, switches live, is remembered, and Dark is unchanged. [PR #34](https://github.com/steven-t0764/CentralRGB/pull/34), [review](https://github.com/steven-t0764/CentralRGB/blob/d5c040c/docs/review-theme-toggle.md)
- **Light mode polish:** slider knobs, white swatches, Breathing fade and the dark flash on switch are fixed. [PR #35](https://github.com/steven-t0764/CentralRGB/pull/35)

## Still not working or not proven

- **Mouse warning too broad:** plain Logitech, HP, ASUS or Corsair mice with no RGB get a permanent "Mouse not detected" warning. Missing wireless RGB mice behind a receiver are not reported. [Review findings 1-2](https://github.com/steven-t0764/CentralRGB/blob/e2852c4/docs/review-device-detection.md)
- **FPS overlay may flash:** the panel-colour background from the black-flash fix also reaches the see-through FPS overlay, so it may show a solid rectangle for a frame on Windows. [Review finding 2](https://github.com/steven-t0764/CentralRGB/blob/768a965/docs/review-repaint.md)
- **Black flash on the real PC unproven:** the frame check can't reproduce the Windows bug and also passes on the old code. It needs `tests/restore_check.py` run on the real PC. [Review finding 3](https://github.com/steven-t0764/CentralRGB/blob/768a965/docs/review-repaint.md)
- **RAM on the real PC unproven:** whether OpenRGB finds the Vengeance DDR4 sticks once MSI Center is closed, and how the hardware effects look on them. [Review: needs the real PC](https://github.com/steven-t0764/CentralRGB/blob/main/docs/review-bugfixes.md)
- **FPS counter in real games unproven:** THE FINALS and Rocket League, admin prompts and antivirus. [Review: needs the real PC](https://github.com/steven-t0764/CentralRGB/blob/main/docs/review-bugfixes.md)
- **DDR5 on real hardware untested:** it depends on OpenRGB supporting the kit and board. [Review limitations](https://github.com/steven-t0764/CentralRGB/blob/4135f28/docs/review-ddr5-lighting.md)
- **Light mode polish not reviewed yet:** its review is still pending. [PR #35](https://github.com/steven-t0764/CentralRGB/pull/35)

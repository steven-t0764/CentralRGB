# Review of the Dark / Light appearance toggle

Reviewed on 2026-11-20 against `main` at `37b6a8d` (merge of PR #34, commit `e527a8f`). The dark look was compared
with `cc9004a`, the commit before the merge.

**Verdict: needs changes.** Three small fixes, all in `central_rgb.py`. Nothing is broken: the toggle works live,
it is remembered, old settings open in Dark, and every dark theme is unchanged. But in Light mode two kinds of
control become invisible: slider knobs while you hover or drag them, and the white colour swatch. That fails the
"no invisible" check. Item 3 is cosmetic and can wait if the owner prefers.

## What I checked

| Check | Result |
| --- | --- |
| `xvfb-run -a python -m unittest discover tests` (Python 3.12, CustomTkinter, Pillow) | **142 tests, OK** |
| `tests/preview.py` and `tests/preview.py --appearance light` | Both run cleanly and save all 8 pages |
| Toggle switches live, no restart | Yes. I ran Dark to Light and Light to Dark, each from Settings, on Gunmetal and Nebula Glass. No callback errors. Afterwards every page matched a fresh start in that mode, except for live graph values. Nothing was left in the old colours. |
| Remembered after reopening | Yes. `settings.json` gets `"appearance"`, and a new start with it seeded opens in that mode (all 9 themes) |
| Old `settings.json` with no `appearance` key | Opens in Dark (`appearance_of`, and `test_appearance.py` covers it) |
| Every dark theme unchanged | **Yes.** I dumped `SOLID`, the accent and chart colours, `GRAD`, the border, `DEFAULT_ACCENT` and `OK/WARN/BAD/INFO` after `_apply_theme(key)` for all 9 themes on `cc9004a` and on `37b6a8d`, and the output is byte-identical. I also took screenshots of all 8 pages × 9 themes before and after. The only pixels that differ are live sensor values and graphs, plus Settings, where the new Appearance row moves the rows below it down by one row. |
| Light mode, all 8 pages × 9 themes | Readable. Text, cards, charts, LED strips, the warning bars (conflict and missing-device), the Monitor → Advanced sensor tree, dropdowns, scrollbars, the device editor and the Create preset dialog all read correctly. Exceptions are items 1–3 below. |
| FPS overlay | Unchanged and fine. On Windows it draws on a see-through key colour, so the appearance doesn't matter. The Overlay page preview reads correctly in Light. |
| Fan safety | `hw_monitor.py`, the fan code and `tests/test_fan_safety.py` are untouched, and the tests pass |
| DDR5 once-per-boot guard | Untouched (no diff in `rgb_engine.py` or `tests/test_ddr5_guard.py`), and the tests pass |
| Claude/Anthropic lines | None in `e527a8f`, the merge commit or the PR #34 description |
| Docs | `CHANGELOG.md` (Unreleased), `README.md` (feature list, UI section, Settings row) and `tests/README.md` (`test_appearance.py`, `preview.py --appearance/--theme`) were all updated. `tests/test_appearance.py` has the GPL-3.0 header. |

Screenshot names below are the files `tests/preview.py --appearance light --theme <key>` writes (`<page>.png`).
Names starting with `light-` come from extra Light-mode captures I made on the same fake hardware (hover, dialogs,
device editor).

## Problems found

1. **Slider knobs disappear on hover or drag in Light mode.** This affects Lighting (Brightness and Speed), the
   device editor (Brightness and Speed) and Fans (every fan card slider), in every theme.
   Screenshot: `light-lighting-slider-hover.png` (Gunmetal). While the pointer is over a slider, its knob turns
   pure white and is invisible on the near-white card, so you can't see where you're dragging.
   Cause: hover colours are hard-coded to `"white"` at `central_rgb.py:2483` (`slider_row`) and
   `central_rgb.py:1731` (fan card slider).
   **Fix:** use a hover colour that works in both modes: `button_hover_color=P["TEXT"]` for the fan slider, and
   `button_hover_color=self.accent if APPEARANCE == "light" else "white"` in `slider_row`. Dark keeps `"white"`,
   so the dark look is unchanged.

2. **The white colour swatch can't be seen in Light mode, and the soft row is very faint.** This affects the Lighting
   page (colour card, the last swatch in both rows) and the device editor (the last swatch in the colour row), in
   every theme. Screenshots: `lighting.png` (any theme, top-right of the swatch grid) and `light-device-editor.png`.
   The white swatch has a contrast of 1.01–1.10 against the light cards, so it shows as an empty gap. The soft row's
   white, `mix(white, (230, 230, 240))`, is the same.
   Cause: the swatch outline is `P["CARD"]` (`central_rgb.py:2781` and the `<Leave>` handler at `2784` for the
   Lighting page, and `central_rgb.py:3130` for the device editor), so nothing separates a white swatch from the
   card.
   **Fix:** in Light mode, outline the swatches with `P["LINE"]` (1 px), or with `P["BTN_LINE"]` only for
   swatches whose contrast against the card is under 1.5. Keep `P["CARD"]` in Dark so the dark look is unchanged.

3. **Breathing previews fade to black instead of into the panel (cosmetic).** This affects the Lighting effect
   tile "Breathing", the Profiles card "Red breathing" and every live LED strip (Home, Lighting, Devices) while the
   Breathing effect runs. Screenshots: `lighting.png` (Cyber Glitch: the Breathing tile bar is near-black) and
   `profiles.png` (Gunmetal: the Red breathing bar is dark maroon). `LedStrip` draws the dimmed LED colour as is.
   In Dark that blends into the panel. In Light the low point of the breath shows as a hard black bar, which looks
   like a leftover dark element.
   **Fix:** in `LedStrip`, when `APPEARANCE == "light"`, treat brightness as opacity over the panel. Draw
   `mix(bg, full_colour, v)`, where `v = max(r, g, b) / 255` and `full_colour` is the colour scaled back to full
   brightness, instead of drawing the dimmed colour. Keep the current drawing in Dark.

## Notes (no change needed)

- In Gunmetal, a switch that is **on** looks like a single solid pill: the knob is `P["TEXT"]` on the
  `chrome` track. The contrast is 1.3:1 in Light and 1.0:1 in Dark, so this is the same Gunmetal design in both
  modes, not a Light regression. The knob position still shows the state.
- The device drawing in the device editor stays a dark board on a light card. It's a picture of the hardware, so
  that's fine.
- Not fixed here, and the same in Dark: the GPU name on Monitor ("RTX 4070 SU") and the GPU fan subtitle on Fans
  are cut off at 1120 px wide.
- Xvfb has no DWM, so I couldn't check the light title bar (`dark_titlebar(root, False)`) or the Windows accent
  shade "Dark 1". They need a look on the real PC.

## Second pass

Re-checked on 2026-11-20 against `main` at `eda8594` (PR #35, "Light mode polish"). The dark look was compared with
`37b6a8d`, the first review's base.

**Verdict: ready.** All three findings are fixed. Every check from the first review passes again, and Dark is
unchanged. One process slip doesn't touch the app: the PR #35 description ends with a "Generated by Claude Code"
footer, which `CLAUDE.md` forbids. To fix it, edit that line out of the PR description. No code change is needed.

### Findings from the first pass

| # | Finding | Status | How I checked |
| --- | --- | --- | --- |
| 1 | Slider knobs disappear on hover or drag in Light | **Fixed** | `slider_hover()` is now used by `slider_row` (Lighting and the device editor), the fan card slider, the Create preset speed slider and the accent update. I ran the real app on the fake hardware, switched to Light, and hovered and clicked every visible slider on Lighting (2) and Fans (7). The knobs turn `#25262a` / `#1a1a1d`, still clearly visible (`light-fans-slider-hover.png`). Across all 9 themes, hover knob contrast against the card is 7.2–7.8:1 for accent knobs and 16.5–16.9:1 for fan knobs. In Dark it is still `"white"`. |
| 2 | White swatch invisible in Light, soft row faint | **Fixed** | `swatch_outline()` is used for the Lighting swatches (including the `<Leave>` handler) and the device editor row. In `lighting.png` (all 9 themes, Light), both white swatches show as outlined circles. Outline contrast against the card for white and soft white is 2.7–3.1:1 in every theme. In Dark it is still `P["CARD"]`. |
| 3 | Breathing previews fade to black in Light | **Fixed** | `led_on()` is used in `LedStrip`, `EffectTile` and `GlowBar`. In `profiles.png` (Gunmetal, Light), the "Red breathing" bar is now soft red, not maroon. The Breathing tile in `lighting.png` (Cyber Glitch) has no dark bar. A near-black red (25, 0, 0) now draws as a pale pink close to `CARD2` in all 9 themes. Dark drawing is unchanged. |

### Full check repeated

| Check | Result |
| --- | --- |
| `python -m py_compile central_rgb.py` and `xvfb-run -a python -m unittest discover tests` (Python 3.12, CustomTkinter, Pillow) | **150 tests, OK** (the first pass had 142; PR #35 adds the `LightModePolish` tests) |
| Toggle switches live, no restart | Yes. In the real app on the fake hardware (Gunmetal) I switched Dark → Light → Dark from Settings, visiting Lighting, Fans and Monitor in Light. There were **0 callback errors**, the palette switched (`BG` = `#f1f2f6` in Light) and `settings.json` was saved each time. `_window_effects()` now runs before the rebuild, as PR #35 says. |
| Old `settings.json` without `appearance` opens in Dark | Yes (`test_appearance.SavedAppearance` passes) |
| Every dark theme unchanged | **Yes.** Each new helper returns its old value when `APPEARANCE != "light"`, which I checked for all 9 themes, and every new drawing branch only runs in Light. I captured screenshots of all 8 pages × 9 themes in Dark on `37b6a8d` and on `eda8594`. Devices, Overlay, Profiles and Settings are pixel-identical. The pixels that differ on Home, Monitor and Fans are live sensor values and graphs. On Lighting, the only difference is a 4 px row of the animated effect tiles (Breathing, Colour Cycle and Rainbow Wave are caught at a different moment), at the same place in every theme. |
| Every page and the FPS overlay readable in Light | Yes. I checked all 8 pages × 9 themes. Text, cards, charts, swatches, effect tiles, LED strips and the Overlay preview all read correctly. `fps_overlay.py` is unchanged and still draws on a see-through key colour. |
| Fan safety | `hw_monitor.py` and `tests/test_fan_safety.py` have no diff since `37b6a8d`, and the tests pass |
| DDR5 once-per-boot guard | `rgb_engine.py` and `tests/test_ddr5_guard.py` have no diff since `37b6a8d`, and the tests pass |
| Docs | `CHANGELOG.md` has a "Light mode polish" line under Unreleased. `README.md` (the Appearance line) and `tests/README.md` (`test_appearance.py`) are updated. `tests/test_appearance.py` keeps its GPL-3.0 header. |
| Claude/Anthropic lines | The commit `eda8594` is clean. **The PR #35 description is not:** it ends with `_Generated by [Claude Code](https://claude.ai/code)_`. To fix it, edit the PR description to remove that line. |

### Still open (unchanged from the first pass, no action in this task)

- Xvfb has no DWM, so the light title bar and the Windows accent shade still need a look on the real PC.
- The GPU name on Monitor and the GPU fan subtitle on Fans are cut off at 1120 px wide. This happens in Dark too.

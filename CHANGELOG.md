# Changelog

Changes that users will notice, newest first. Agents add a line under **Unreleased** with every change.

## Unreleased
- **RAM not detected:** when other RGB software (MSI Center / Mystic Light, SteelSeries GG, iCUE) holds the RAM's bus, the Devices page now says which program it is and what to do, and RAM detection is retried once after "Close them".
- **RAM flicker:** RGB RAM now updates at a steady, lower rate, one stick at a time on the shared bus, skips frames that wouldn't change anything, and uses the sticks' own hardware modes for Breathing and Color Cycle where they have them.
- **FPS counter:** PresentMon restarts itself if it stops, the counter no longer locks onto launchers, overlays or anti-cheat helpers, and when it can't count it says why (for example "PresentMon needs admin") instead of disappearing.
- **Window restore and page switching:** restoring from the taskbar draws the window while it's hidden so it no longer flashes black, and fast clicks between pages no longer leave a half-built page.

# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
One-click updates from GitHub Releases (standard library only).

* check()        - asks GitHub for the newest real release (drafts, pre-releases and the
                   "Test build" ones are skipped) and says whether it is newer than APP_VERSION.
* download()     - fetches the right file (installer for an installed copy, the portable exe for a
                   portable copy) with progress, and refuses it unless its SHA-256 matches the
                   SHA256SUMS.txt published with the release.
* start_apply()  - starts a small hidden helper that waits for this app to close normally (so fans
                   are handed back to the BIOS exactly as on any close), then runs the installer
                   silently or swaps the portable exe, and opens the new version.

Everything that touches Windows fails quietly elsewhere. Network errors become an UpdateError with
a message that can be shown to the user as-is.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO = "steven-t0764/CentralRGB"
API_RELEASES = f"https://api.github.com/repos/{REPO}/releases?per_page=30"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
LATEST_INSTALLER = f"https://github.com/{REPO}/releases/latest/download/CentralRGB-Setup.exe"
INSTALLER_ASSET = "CentralRGB-Setup.exe"
PORTABLE_ASSET = "Central.RGB.exe"     # GitHub turns the space in "Central RGB.exe" into a dot
CHECKSUM_ASSETS = ("SHA256SUMS.txt", "SHA256SUMS")
APP_ID = "{8C1F2E7A-5B3D-4C8E-9A61-2F7D3B9E4C10}_is1"   # Inno Setup uninstall key (AppId in central_rgb.iss)
TIMEOUT = 15            # seconds, for every request
CHECK_EVERY = 24 * 3600  # automatic checks: at most once a day
INSTALLER_ARGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELAUNCH=1"]
IS_WIN = os.name == "nt"

# settings.json keys (absent in older settings files, which then use the defaults)
AUTO_KEY = "auto_update_check"       # bool, default on
LAST_KEY = "last_update_check"       # unix time of the last automatic check


class UpdateError(Exception):
    """Something went wrong; str(e) is a plain message for the user."""


@dataclass
class Release:
    tag: str
    version: tuple
    name: str = ""
    page: str = RELEASES_PAGE
    assets: dict = field(default_factory=dict)    # asset name -> download URL
    notes: str = ""


@dataclass
class CheckResult:
    current: str
    latest: Release | None
    newer: bool

    @property
    def message(self) -> str:
        if self.latest is None:
            return "No releases found."
        if self.newer:
            return f"Central RGB {self.latest.tag.lstrip('vV')} is available (you have {self.current})."
        return f"You're on the latest version ({self.current})."


# --------------------------------------------------------------------------- versions
def parse_version(text: str) -> tuple:
    """'v2.10.1' -> (2, 10, 1, 1). A suffix such as '-beta' sorts before the plain release:
    '2.4.0-beta' -> (2, 4, 0, 0). Unparseable text -> ()."""
    m = re.match(r"^\s*[vV]?(\d+(?:\.\d+)*)(.*)$", str(text or ""))
    if not m:
        return ()
    nums = [int(x) for x in m.group(1).split(".")]
    while len(nums) < 3:
        nums.append(0)
    while len(nums) > 3 and nums[-1] == 0:
        nums.pop()
    final = 0 if m.group(2).strip(" .") else 1
    return tuple(nums) + (final,)


def is_newer(tag: str, current: str) -> bool:
    new, cur = parse_version(tag), parse_version(current)
    return bool(new) and (not cur or new > cur)


# --------------------------------------------------------------------------- GitHub
def _open(url: str, opener, accept="application/vnd.github+json"):
    req = urllib.request.Request(url, headers={"User-Agent": "CentralRGB-updater", "Accept": accept})
    try:
        return opener(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        remaining = e.headers.get("X-RateLimit-Remaining") if e.headers is not None else None
        if e.code == 429 or (e.code == 403 and str(remaining) == "0"):
            raise UpdateError("GitHub's limit on update checks was reached. Try again in an hour.") from None
        if e.code == 404:
            raise UpdateError("No releases were found on GitHub.") from None
        raise UpdateError(f"GitHub answered with an error ({e.code}). Try again later.") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        reason = getattr(e, "reason", e)
        raise UpdateError(f"Couldn't reach GitHub to check for updates (offline?): {reason}") from None


def _is_real_release(r: dict) -> bool:
    if not isinstance(r, dict) or r.get("draft") or r.get("prerelease"):
        return False
    tag, name = str(r.get("tag_name") or ""), str(r.get("name") or "")
    if tag.lower().startswith("test") or name.lower().startswith("test build"):
        return False
    return bool(parse_version(tag))


def latest_release(opener=urllib.request.urlopen) -> Release | None:
    """Newest real release on GitHub, or None if there is none."""
    with _open(API_RELEASES, opener) as resp:
        try:
            data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            raise UpdateError("GitHub sent an answer the updater couldn't read. Try again later.") from None
    if not isinstance(data, list):
        raise UpdateError("GitHub sent an answer the updater couldn't read. Try again later.")
    best = None
    for r in data:
        if not _is_real_release(r):
            continue
        v = parse_version(r["tag_name"])
        if best is None or v > best.version:
            assets = {a.get("name"): a.get("browser_download_url") for a in r.get("assets") or []
                      if isinstance(a, dict) and a.get("name") and a.get("browser_download_url")}
            best = Release(tag=r["tag_name"], version=v, name=r.get("name") or r["tag_name"],
                           page=r.get("html_url") or RELEASES_PAGE, assets=assets, notes=r.get("body") or "")
    return best


def check(current: str, opener=urllib.request.urlopen) -> CheckResult:
    rel = latest_release(opener)
    return CheckResult(current=current, latest=rel, newer=bool(rel and is_newer(rel.tag, current)))


# --------------------------------------------------------------------------- which copy is running
def _registry_install_dir() -> Path | None:
    if not IS_WIN:
        return None
    try:
        import winreg
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
                try:
                    with winreg.OpenKey(hive, rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}",
                                        0, winreg.KEY_READ | view) as k:
                        loc = winreg.QueryValueEx(k, "InstallLocation")[0]
                        if loc:
                            return Path(loc)
                except OSError:
                    continue
    except Exception:
        return None
    return None


def install_kind(exe: str | None = None, frozen: bool | None = None, meipass: str | None = None,
                 registry_dir: Path | None | bool = False) -> str:
    """'installed' (setup put it there), 'portable' (the single-file exe) or 'source' (python script)."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if not frozen:
        return "source"
    exe_path = Path(exe or sys.executable).resolve()
    meipass = getattr(sys, "_MEIPASS", None) if meipass is None else meipass
    if meipass and Path(meipass).name.startswith("_MEI"):
        return "portable"                          # the single file unpacks itself; setup never ships it
    if any((exe_path.parent / f"unins{i:03d}.exe").exists() for i in range(3)):
        return "installed"
    reg = _registry_install_dir() if registry_dir is False else registry_dir
    try:
        if reg and Path(reg).resolve() == exe_path.parent:
            return "installed"
    except Exception:
        pass
    return "portable"                              # a folder build copied somewhere by hand


def asset_for(kind: str) -> str | None:
    return {"installed": INSTALLER_ASSET, "portable": PORTABLE_ASSET}.get(kind)


def pick_asset(release: Release, kind: str) -> tuple[str, str]:
    """(asset name, download URL) for this kind of copy, or UpdateError."""
    want = asset_for(kind)
    if want is None:
        raise UpdateError("This copy runs from source; update it with git pull or download the installer.")
    for name, url in release.assets.items():
        if _norm(name) == _norm(want):
            return name, url
    raise UpdateError(f"Release {release.tag} has no {want} to download.")


def _norm(name: str) -> str:
    return str(name).strip().lstrip("*").replace(" ", ".").lower()


# --------------------------------------------------------------------------- checksums + download
def parse_checksums(text: str) -> dict:
    """'<sha256>  <file>' lines (sha256sum / Get-FileHash style) -> {normalized file name: sha256}."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\s*([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m:
            out[_norm(Path(m.group(2).replace("\\", "/")).name)] = m.group(1).lower()
    return out


def expected_sha256(release: Release, asset_name: str, opener=urllib.request.urlopen) -> str:
    for name in CHECKSUM_ASSETS:
        url = next((u for n, u in release.assets.items() if _norm(n) == _norm(name)), None)
        if url:
            with _open(url, opener, accept="application/octet-stream") as resp:
                sums = parse_checksums(resp.read().decode("utf-8", "replace"))
            sha = sums.get(_norm(asset_name))
            if sha:
                return sha
            raise UpdateError(f"The release's checksum list doesn't include {asset_name}, so it won't be installed.")
    per_file = next((u for n, u in release.assets.items() if _norm(n) == _norm(asset_name + ".sha256")), None)
    if per_file:
        with _open(per_file, opener, accept="application/octet-stream") as resp:
            m = re.search(r"[0-9a-fA-F]{64}", resp.read().decode("utf-8", "replace"))
        if m:
            return m.group(0).lower()
    raise UpdateError(f"Release {release.tag} has no published checksum, so the download can't be "
                      "verified and won't be installed.")


def download(release: Release, kind: str, dest_dir: Path, progress=None,
             opener=urllib.request.urlopen) -> Path:
    """Download and verify the file for `kind`. progress(done_bytes, total_bytes_or_0) is called as it
    goes. Returns the verified file; on a checksum mismatch the file is deleted and UpdateError raised."""
    name, url = pick_asset(release, kind)
    want = expected_sha256(release, name, opener)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / ("CentralRGB-Setup-update.exe" if kind == "installed" else "Central RGB.exe.new")
    part = final.with_name(final.name + ".part")
    h = hashlib.sha256()
    done = 0
    try:
        with _open(url, opener, accept="application/octet-stream") as resp, open(part, "wb") as f:
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except Exception:
                total = 0
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except UpdateError:
        _rm(part)
        raise
    except Exception as e:
        _rm(part)
        raise UpdateError(f"The download stopped part-way ({e}). Try again.") from None
    got = h.hexdigest()
    if got != want:
        _rm(part)
        raise UpdateError(f"The downloaded {name} doesn't match the checksum published with {release.tag} "
                          f"(expected {want[:12]}..., got {got[:12]}...), so it was deleted and not installed.")
    _rm(final)
    part.replace(final)
    return final


def _rm(p: Path):
    try:
        Path(p).unlink()
    except Exception:
        pass


def download_dir(kind: str, exe: str | None = None) -> Path:
    """Installer: a temp folder. Portable: next to the exe (so the swap is a rename on the same drive),
    or a temp folder when that folder isn't writable."""
    tmp = Path(tempfile.gettempdir()) / "CentralRGB-update"
    if kind == "portable":
        here = Path(exe or sys.executable).resolve().parent
        try:
            probe = here / ".centralrgb-write-test"
            probe.write_bytes(b"")
            probe.unlink()
            return here
        except Exception:
            return tmp
    return tmp


# --------------------------------------------------------------------------- applying
def _ps_quote(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def helper_script(kind: str, pid: int, new_file: Path, exe: str | None = None) -> str:
    """PowerShell run by the hidden helper. It waits for `pid` (this app) to finish closing first."""
    exe = str(Path(exe or sys.executable).resolve())
    wait = f"Wait-Process -Id {int(pid)} -Timeout 120 -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 800"
    if kind == "installed":
        args = ",".join(_ps_quote(a) for a in INSTALLER_ARGS)
        return (f"{wait}; Start-Process -FilePath {_ps_quote(new_file)} -ArgumentList {args} -Wait; "
                f"Remove-Item -LiteralPath {_ps_quote(new_file)} -Force -ErrorAction SilentlyContinue")
    if kind == "portable":
        old = exe + ".old"
        return (f"{wait}; $ok = $false; for ($i = 0; $i -lt 40 -and -not $ok; $i++) {{ try {{ "
                f"if (Test-Path -LiteralPath {_ps_quote(old)}) {{ Remove-Item -LiteralPath {_ps_quote(old)} -Force }}; "
                f"Move-Item -LiteralPath {_ps_quote(exe)} -Destination {_ps_quote(old)} -Force -ErrorAction Stop; "
                f"Move-Item -LiteralPath {_ps_quote(new_file)} -Destination {_ps_quote(exe)} -Force -ErrorAction Stop; "
                f"$ok = $true }} catch {{ if (-not (Test-Path -LiteralPath {_ps_quote(exe)}) -and "
                f"(Test-Path -LiteralPath {_ps_quote(old)})) {{ Move-Item -LiteralPath {_ps_quote(old)} "
                f"-Destination {_ps_quote(exe)} -Force }}; Start-Sleep -Milliseconds 500 }} }}; "
                f"$env:PYINSTALLER_RESET_ENVIRONMENT = '1'; Start-Process -FilePath {_ps_quote(exe)} -ArgumentList '--restarted'; "
                f"if ($ok) {{ Start-Sleep -Seconds 10; Remove-Item -LiteralPath {_ps_quote(old)} -Force -ErrorAction SilentlyContinue }}")
    raise UpdateError("This copy can't update itself.")


def helper_command(kind: str, pid: int, new_file: Path, exe: str | None = None) -> list[str]:
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden", "-Command", helper_script(kind, pid, new_file, exe)]


def start_apply(kind: str, new_file: Path, exe: str | None = None, env: dict | None = None) -> None:
    """Start the helper. The caller must then close the app through its normal exit path."""
    if not IS_WIN:
        raise UpdateError("Installing updates is only available on Windows.")
    env = dict(env if env is not None else os.environ)
    for k in list(env):                   # the portable exe's unpack folder must not leak to the new copy
        if k.startswith("_PYI_") or k.startswith("_MEIPASS"):
            env.pop(k, None)
    try:
        subprocess.Popen(helper_command(kind, os.getpid(), Path(new_file), exe), env=env,
                         creationflags=0x08000000 | 0x00000008,   # CREATE_NO_WINDOW | DETACHED_PROCESS
                         close_fds=True)
    except Exception as e:
        raise UpdateError(f"Couldn't start the update ({e}).") from None


# --------------------------------------------------------------------------- automatic checks
def auto_check_enabled(data: dict) -> bool:
    return bool(data.get(AUTO_KEY, True))


def should_auto_check(data: dict, now: float | None = None) -> bool:
    """On (the default) and the last automatic check is at least a day old."""
    if not auto_check_enabled(data):
        return False
    now = time.time() if now is None else now
    try:
        last = float(data.get(LAST_KEY) or 0)
    except (TypeError, ValueError):
        last = 0.0
    return last > now or now - last >= CHECK_EVERY   # a clock that went backwards also allows a check

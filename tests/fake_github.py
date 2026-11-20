# Central RGB - control all your PC's RGB lighting, fans and system monitoring from one app.
# Copyright (C) 2026 steven-t0764
#
# This program is free software: you can redistribute it and/or modify it under the terms of the
# GNU General Public License as published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version. It is distributed WITHOUT ANY WARRANTY; see the
# GNU General Public License for more details: <https://www.gnu.org/licenses/>.
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Fake GitHub Releases API for the updater tests and previews (no network).

    gh = FakeGitHub()                      # a 2.9.0 release, an older one, a draft, a pre-release and test-build
    upd.check("2.3.2", opener=gh)          # pass it wherever updater takes `opener`
    gh.offline = True / gh.rate_limited = True / gh.files["Central.RGB.exe"] = b"tampered"
"""
from __future__ import annotations

import email.message
import hashlib
import io
import json
import urllib.error

BASE = "https://github.com/steven-t0764/CentralRGB/releases/download"


class _Resp(io.BytesIO):
    def __init__(self, body: bytes):
        super().__init__(body)
        self.headers = email.message.Message()
        self.headers["Content-Length"] = str(len(body))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _release(tag, files, *, draft=False, prerelease=False, name=None, sums=True):
    assets = [{"name": n, "browser_download_url": f"{BASE}/{tag}/{n}"} for n in files]
    if sums:
        assets.append({"name": "SHA256SUMS.txt", "browser_download_url": f"{BASE}/{tag}/SHA256SUMS.txt"})
    return {"tag_name": tag, "name": name or tag, "draft": draft, "prerelease": prerelease,
            "html_url": f"https://github.com/steven-t0764/CentralRGB/releases/tag/{tag}", "body": "", "assets": assets}


class FakeGitHub:
    """Callable like urllib.request.urlopen(req, timeout=...)."""

    def __init__(self, latest="v2.9.0"):
        self.offline = False
        self.rate_limited = False
        self.requests: list[str] = []
        self.files = {"CentralRGB-Setup.exe": b"MZ fake installer " * 1000, "Central.RGB.exe": b"MZ fake portable " * 900}
        self.releases = [
            _release("test-build", list(self.files), prerelease=True, name="Test build (not a release)"),
            _release("v3.0.0-beta", list(self.files), prerelease=True),
            _release("v4.0.0", list(self.files), draft=True),
            _release(latest, list(self.files)),
            _release("v2.3.2", list(self.files)),
        ]
        self.sums_override: str | None = None

    def sums(self) -> str:
        if self.sums_override is not None:
            return self.sums_override
        return "".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in self.files.items())

    def __call__(self, req, timeout=None):
        assert timeout, "the updater must always pass a timeout"
        url = req.full_url if hasattr(req, "full_url") else str(req)
        self.requests.append(url)
        if self.offline:
            raise urllib.error.URLError("[Errno 11001] getaddrinfo failed")
        if self.rate_limited:
            hdrs = email.message.Message()
            hdrs["X-RateLimit-Remaining"] = "0"
            raise urllib.error.HTTPError(url, 403, "rate limit exceeded", hdrs, io.BytesIO(b"{}"))
        if url.startswith("https://api.github.com/repos/steven-t0764/CentralRGB/releases"):
            return _Resp(json.dumps(self.releases).encode())
        name = url.rsplit("/", 1)[-1]
        if name == "SHA256SUMS.txt":
            return _Resp(self.sums().encode())
        if name in self.files:
            return _Resp(self.files[name])
        raise urllib.error.HTTPError(url, 404, "Not Found", email.message.Message(), io.BytesIO(b""))

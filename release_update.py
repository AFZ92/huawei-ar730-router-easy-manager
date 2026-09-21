"""Small, dependency-free GitHub Release update checker.

This module deliberately uses the standard library: the application must still be
able to check for an update when an optional network dependency is unavailable.
"""
import json
import os
import platform
import re
import urllib.error
import urllib.request


GITHUB_REPOSITORY = "AFZ92/huawei-ar730-router-easy-manager"
LATEST_RELEASE_API = "https://api.github.com/repos/%s/releases/latest" % GITHUB_REPOSITORY


def version_key(version):
    """Return a SemVer-like tuple suitable for this project's release tags."""
    text = str(version or "").strip().lstrip("vV")
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$", text)
    return tuple(int(part) for part in match.groups()) if match else None


def is_newer(candidate, installed):
    candidate_key, installed_key = version_key(candidate), version_key(installed)
    return bool(candidate_key and installed_key and candidate_key > installed_key)


def platform_asset_name(assets=None):
    """Return the release artifact expected by the current platform/CPU."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    x64 = machine in ("amd64", "x86_64", "x64")
    if system == "windows" and x64:
        return "AR730Manager-Windows-x64-Setup.exe"
    if system == "darwin":
        return "AR730Manager-macOS-%s.zip" % ("arm64" if machine in ("arm64", "aarch64") else "x64")
    return None


def check_for_update(installed_version, timeout=4):
    """Fetch the latest public release; failures are intentionally non-fatal."""
    api_url = os.environ.get("AR730_UPDATE_API", LATEST_RELEASE_API)
    request = urllib.request.Request(api_url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "AR730Manager/%s" % installed_version,
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            release = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.HTTPError, urllib.error.URLError):
        return None

    tag = release.get("tag_name", "")
    if release.get("draft") or release.get("prerelease") or not is_newer(tag, installed_version):
        return None
    assets = {asset.get("name"): asset for asset in release.get("assets", [])}
    asset_name = platform_asset_name(assets)
    # A release is not offered on an unsupported platform or until its matching
    # artifact has finished uploading.
    if not asset_name or asset_name not in assets or "SHA256SUMS.txt" not in assets:
        return None
    return {
        "version": tag.lstrip("vV"),
        "release_url": release.get("html_url", "https://github.com/%s/releases/latest" % GITHUB_REPOSITORY),
        "asset": assets[asset_name],
        "checksums": assets["SHA256SUMS.txt"],
    }

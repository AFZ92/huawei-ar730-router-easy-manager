"""Small, dependency-free GitHub Release update checker.

This module deliberately uses the standard library: the application must still be
able to check for an update when an optional network dependency is unavailable.
"""
import json
import hashlib
import os
import platform
import re
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


GITHUB_REPOSITORY = "AFZ92/huawei-ar730-router-easy-manager"
LATEST_RELEASE_API = "https://api.github.com/repos/%s/releases/latest" % GITHUB_REPOSITORY


def _asset_url(asset):
    """Return the public download URL from a GitHub Release asset."""
    return asset.get("browser_download_url") or asset.get("url") or ""


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


def _checksum_for(name, text):
    """Read one GNU sha256sum entry without accepting a partial filename match."""
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[-1].lstrip("*") == name:
            digest = fields[0].lower()
            if re.match(r"^[0-9a-f]{64}$", digest):
                return digest
    return None


def download_and_verify(update, directory, timeout=30):
    """Download the selected artifact and verify it against the release manifest."""
    asset, checksums = update["asset"], update["checksums"]
    name = asset.get("name", "")
    asset_url, sums_url = _asset_url(asset), _asset_url(checksums)
    if not name or not asset_url or not sums_url:
        raise RuntimeError("The release is missing a usable download URL.")
    request_headers = {"User-Agent": "AR730Manager-updater"}
    with urllib.request.urlopen(urllib.request.Request(sums_url, headers=request_headers), timeout=timeout) as response:
        expected = _checksum_for(name, response.read().decode("utf-8"))
    if not expected:
        raise RuntimeError("The release checksum manifest has no entry for %s." % name)
    destination = os.path.join(directory, name)
    digest = hashlib.sha256()
    with urllib.request.urlopen(urllib.request.Request(asset_url, headers=request_headers), timeout=timeout) as response:
        with open(destination, "wb") as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                digest.update(block)
                output.write(block)
    if digest.hexdigest().lower() != expected:
        try:
            os.remove(destination)
        except OSError:
            pass
        raise RuntimeError("SHA-256 verification failed; the update was not installed.")
    return destination


def _wait_for_exit(pid):
    """Wait briefly for the application which requested this update to close."""
    if not pid or pid == os.getpid():
        return
    for unused in range(120):
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.25)
    raise RuntimeError("The application did not close before the update timed out.")


def _update_plan(update, relaunch_path):
    return {
        "asset": {"name": update["asset"].get("name"), "url": _asset_url(update["asset"])},
        "checksums": {"name": "SHA256SUMS.txt", "url": _asset_url(update["checksums"])},
        "relaunch_path": relaunch_path,
    }


def apply_windows_update(plan, parent_pid=0):
    """Run from a copied executable after the UI has closed on Windows."""
    _wait_for_exit(int(parent_pid or 0))
    work = tempfile.mkdtemp(prefix="ar730-manager-update-")
    update = {
        "asset": {"name": plan["asset"]["name"], "browser_download_url": plan["asset"]["url"]},
        "checksums": {"name": "SHA256SUMS.txt", "browser_download_url": plan["checksums"]["url"]},
    }
    installer = download_and_verify(update, work)
    completed = subprocess.run([installer, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], check=False)
    if completed.returncode != 0:
        raise RuntimeError("The Windows installer returned error %s." % completed.returncode)
    subprocess.Popen([plan["relaunch_path"]], close_fds=True)


def _macos_updater_script(plan, parent_pid, app_bundle):
    """Build a detached, shell-only macOS updater for a bundled app.

    A shell helper is necessary because a running .app cannot overwrite its own
    executable. It asks for macOS authorization only when the app is installed
    in a protected directory such as /Applications.
    """
    work = tempfile.mkdtemp(prefix="ar730-manager-update-")
    artifact = plan["asset"]["name"]
    quoted = shlex.quote
    target_parent = os.path.dirname(app_bundle)
    install = "/bin/rm -rf {target} && /usr/bin/ditto {source} {target}".format(
        source=quoted(os.path.join(work, "unpacked", "AR730Manager.app")), target=quoted(app_bundle))
    install_step = (install if os.access(target_parent, os.W_OK) else
                    "/usr/bin/osascript -e %s" % quoted("do shell script " + json.dumps(install) + " with administrator privileges"))
    return """#!/bin/sh
set -eu
parent={parent}
while /bin/kill -0 "$parent" 2>/dev/null; do /bin/sleep 1; done
work={work}
trap '/bin/rm -rf "$work"' EXIT
artifact={artifact}
/usr/bin/curl -fL {asset_url} -o "$work/$artifact"
/usr/bin/curl -fL {sums_url} -o "$work/SHA256SUMS.txt"
expected=$(/usr/bin/awk -v name="$artifact" '$2 == name {{ print $1 }}' "$work/SHA256SUMS.txt")
actual=$(/usr/bin/shasum -a 256 "$work/$artifact" | /usr/bin/awk '{{ print $1 }}')
[ -n "$expected" ] && [ "$expected" = "$actual" ]
/usr/bin/ditto -x -k "$work/$artifact" "$work/unpacked"
{install_step}
/usr/bin/open -a {target}
""".format(parent=int(parent_pid), work=quoted(work), artifact=quoted(artifact),
           asset_url=quoted(plan["asset"]["url"]), sums_url=quoted(plan["checksums"]["url"]),
           install_step=install_step, target=quoted(app_bundle))


def launch_update(update, executable=None):
    """Detach a platform updater and return ``(ok, error_message)``.

    The caller must close its GUI immediately after this returns successfully.
    """
    executable = os.path.abspath(executable or sys.executable)
    if not getattr(sys, "frozen", False):
        return False, "Automatic updates are available only from an installed application."
    plan = _update_plan(update, executable)
    if os.name == "nt":
        work = tempfile.mkdtemp(prefix="ar730-manager-updater-")
        helper = os.path.join(work, "AR730Manager-Updater.exe")
        shutil.copy2(executable, helper)
        subprocess.Popen([helper, "--apply-update", str(os.getpid()), json.dumps(plan)], close_fds=True)
        return True, ""
    if platform.system() == "Darwin":
        marker = os.sep + "Contents" + os.sep + "MacOS" + os.sep
        if marker not in executable:
            return False, "The installed macOS app bundle could not be located."
        app_bundle = executable.split(marker, 1)[0]
        script_path = os.path.join(tempfile.mkdtemp(prefix="ar730-manager-updater-"), "update.sh")
        with open(script_path, "w", encoding="utf-8") as script:
            script.write(_macos_updater_script(plan, os.getpid(), app_bundle))
        os.chmod(script_path, 0o700)
        subprocess.Popen(["/bin/sh", script_path], close_fds=True)
        return True, ""
    return False, "Automatic updates are not supported on this platform."

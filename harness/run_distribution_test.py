"""Offline checks for release-version and update eligibility logic."""
import io
import json
import os
import sys
import tempfile
from pathlib import Path

APPDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APPDIR)
import release_update as updates  # noqa: E402

fails = []


def check(label, condition):
    print(("  ✓ " if condition else "  ✗ ") + label)
    if not condition:
        fails.append(label)


check("SemVer compares a patch release", updates.is_newer("v1.0.1", "1.0.0"))
check("SemVer rejects the installed release", not updates.is_newer("1.0.0", "1.0.0"))
check("SemVer rejects malformed tags", not updates.is_newer("latest", "1.0.0"))

payload = {
    "tag_name": "v1.2.0", "html_url": "https://example.invalid/releases/v1.2.0",
    "assets": [
        {"name": "AR730Manager-Windows-x64-Setup.exe", "browser_download_url": "https://example.invalid/setup"},
        {"name": "SHA256SUMS.txt", "browser_download_url": "https://example.invalid/sums"},
    ],
}


class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *unused): self.close()


original_open = updates.urllib.request.urlopen
original_system = updates.platform.system
original_machine = updates.platform.machine
updates.urllib.request.urlopen = lambda *args, **kwargs: Response(json.dumps(payload).encode("utf-8"))
updates.platform.system = lambda: "Windows"
updates.platform.machine = lambda: "AMD64"
try:
    found = updates.check_for_update("1.0.0")
finally:
    updates.urllib.request.urlopen = original_open
    updates.platform.system = original_system
    updates.platform.machine = original_machine

check("Matching platform release is offered", found and found["version"] == "1.2.0")
check("Matching installer is selected", found and found["asset"]["name"].endswith("Setup.exe"))


class DownloadResponse(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *unused): self.close()


artifact = b"verified update artifact"
checksum = __import__("hashlib").sha256(artifact).hexdigest()
download_payloads = {
    "https://example.invalid/sums": (checksum + "  AR730Manager-Windows-x64-Setup.exe\n").encode("utf-8"),
    "https://example.invalid/setup": artifact,
}
original_open = updates.urllib.request.urlopen
updates.urllib.request.urlopen = lambda request, **kwargs: DownloadResponse(download_payloads[request.full_url])
try:
    with tempfile.TemporaryDirectory() as directory:
        downloaded = updates.download_and_verify({
            "asset": {"name": "AR730Manager-Windows-x64-Setup.exe", "browser_download_url": "https://example.invalid/setup"},
            "checksums": {"name": "SHA256SUMS.txt", "browser_download_url": "https://example.invalid/sums"},
        }, directory)
        check("Automatic updater verifies SHA-256 before returning an installer", Path(downloaded).read_bytes() == artifact)
finally:
    updates.urllib.request.urlopen = original_open

mac_script = updates._macos_updater_script({
    "asset": {"name": "AR730Manager-macOS-arm64.zip", "url": "https://example.invalid/app.zip"},
    "checksums": {"name": "SHA256SUMS.txt", "url": "https://example.invalid/sums"},
}, 123, "/Applications/AR730Manager.app")
check("macOS updater waits for the app, verifies SHA-256, then relaunches", "/bin/kill -0" in mac_script and "shasum -a 256" in mac_script and "/usr/bin/open -a" in mac_script)
check("macOS updater requests authorization only for protected install paths", "with administrator privileges" in mac_script)

release_builder = Path(APPDIR, "build", "release.py").read_text(encoding="utf-8")
icon_builder = Path(APPDIR, "build", "create_app_icons.py").read_text(encoding="utf-8")
check("Release build assigns the AFZ icon to PyInstaller", '"--icon", str(icon)' in release_builder)
check("Native AFZ icon source is generated for Windows and macOS",
      '"afz-logo.ico"' in icon_builder and '"afz-logo.icns"' in icon_builder)
check("macOS bundle receives the application version", "CFBundleShortVersionString" in release_builder)
qt_source = Path(APPDIR, "ar730_qt.py").read_text(encoding="utf-8")
check("Update approval starts the external updater rather than opening a browser", "legacy.launch_update(update)" in qt_source)
if fails:
    raise SystemExit("FAILED: " + ", ".join(fails))

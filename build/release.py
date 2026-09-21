#!/usr/bin/env python3
"""Create the native artifact for the host used by the release workflow."""
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
NAME = "AR730Manager"


def run(*args):
    subprocess.run(args, cwd=ROOT, check=True)


def configure_macos_bundle(app, version):
    """Give the shipped .app stable AFZ metadata after PyInstaller creates it."""
    info_path = app / "Contents" / "Info.plist"
    with info_path.open("rb") as info_file:
        info = plistlib.load(info_file)
    info.update({
        "CFBundleDisplayName": "AR730 Manager",
        "CFBundleIdentifier": "com.afzsystems.ar730manager",
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
    })
    with info_path.open("wb") as info_file:
        plistlib.dump(info, info_file)
    # Re-sign because editing Info.plist invalidates PyInstaller's ad-hoc signature.
    run("codesign", "--force", "--deep", "--sign", "-", str(app))


def main():
    system = platform.system()
    DIST.mkdir(exist_ok=True)
    source = (ROOT / "ar730_manager.py").read_text(encoding="utf-8")
    match = re.search(r'^APP_VERSION = "([^"]+)"$', source, re.MULTILINE)
    if not match:
        raise RuntimeError("APP_VERSION is missing from ar730_manager.py")
    version = match.group(1)
    tagged_version = os.environ.get("AR730_VERSION", "").lstrip("vV")
    if re.match(r"^\d+\.\d+\.\d+$", tagged_version) and version != tagged_version:
        raise RuntimeError("AR730_VERSION tag must match APP_VERSION in ar730_manager.py")
    separator = ";" if system == "Windows" else ":"
    run(sys.executable, "build/create_app_icons.py")
    icon = ROOT / "build" / "icons" / ("afz-logo.ico" if system == "Windows" else "afz-logo.icns")
    if not icon.is_file():
        raise RuntimeError("AFZ application icon was not created: %s" % icon)
    common = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
              "--name", NAME, "--icon", str(icon), "--add-data", "data%sdata" % separator,
              "--add-data", "assets%sassets" % separator]
    # The maintained production interface is the Qt application. Its legacy
    # router engine is imported transitively and therefore bundled as well.
    if system == "Windows":
        run(*(common + ["--onefile", "--windowed", "ar730_qt.py"]))
        portable = DIST / (NAME + ".exe")
        portable.rename(DIST / "AR730Manager-Windows-x64.exe")
        iscc = shutil.which("iscc")
        if not iscc:
            raise RuntimeError("Inno Setup (iscc) is required for the Windows installer")
        run(iscc, "/DSourceExe=%s" % (DIST / "AR730Manager-Windows-x64.exe"),
            "/O%s" % DIST, "/FAR730Manager-Windows-x64-Setup", "packaging/windows/AR730Manager.iss")
    elif system == "Darwin":
        arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x64"
        run(*(common + ["--windowed", "ar730_qt.py"]))
        app = DIST / (NAME + ".app")
        configure_macos_bundle(app, version)
        archive_base = DIST / ("AR730Manager-macOS-" + arch)
        shutil.make_archive(str(archive_base), "zip", DIST, app.name)
        shutil.rmtree(app)
    else:
        raise RuntimeError("Release builds must run on Windows or macOS")


if __name__ == "__main__":
    main()

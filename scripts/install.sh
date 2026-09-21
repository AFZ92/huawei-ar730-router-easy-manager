#!/usr/bin/env bash
# One-command macOS installer. Run with:
# curl -fsSL https://raw.githubusercontent.com/AFZ92/huawei-ar730-router-easy-manager/main/scripts/install.sh | bash
set -euo pipefail
repo="AFZ92/huawei-ar730-router-easy-manager"
arch="$(uname -m)"
case "$arch" in arm64) artifact="AR730Manager-macOS-arm64.zip";; x86_64) artifact="AR730Manager-macOS-x64.zip";; *) echo "Unsupported macOS architecture: $arch" >&2; exit 1;; esac
asset_url="https://github.com/$repo/releases/latest/download/$artifact"
sums_url="https://github.com/$repo/releases/latest/download/SHA256SUMS.txt"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
curl -fL "$asset_url" -o "$work/$artifact"; curl -fL "$sums_url" -o "$work/SHA256SUMS.txt"
expected="$(awk -v name="$artifact" '$2 == name { print $1 }' "$work/SHA256SUMS.txt")"
actual="$(shasum -a 256 "$work/$artifact" | awk '{ print $1 }')"
[ -n "$expected" ] && [ "$expected" = "$actual" ] || { echo "SHA-256 verification failed. Nothing was installed." >&2; exit 1; }
ditto -x -k "$work/$artifact" "$work/unpacked"
# A per-user application directory keeps later in-app updates free of an
# administrator-password prompt. User data is stored separately by the app.
target="$HOME/Applications/AR730Manager.app"
mkdir -p "$HOME/Applications"
rm -rf "$target"
ditto "$work/unpacked/AR730Manager.app" "$target"
open -a "$target"

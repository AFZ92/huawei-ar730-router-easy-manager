#!/bin/sh
# Builds the zip that "portal local-server load flash:/<name>.zip" expects.
# The router serves only what is inside the zip, flat at its root, so every page
# the firmware may redirect to must be present (login.html is a copy of index.html).
#
#   docs/portal/afz-portal/build.sh [version]   ->  build/portal_afz_<version>.zip
set -e
here=$(cd "$(dirname "$0")" && pwd)
out_dir="$(cd "$here/../../.." && pwd)/build"
version=${1:-$(date +%Y%m%d%H%M)}
out="$out_dir/portal_afz_$version.zip"

mkdir -p "$out_dir"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
cp "$here/index.html" "$here/auth_success.html" "$here/hasonline.html" "$here/logout.html" "$tmp/"
cp "$here/index.html" "$tmp/login.html"
rm -f "$out"
(cd "$tmp" && zip -X -q "$out" index.html login.html auth_success.html hasonline.html logout.html)
unzip -l "$out"
echo "Upload with:  sftp admin@<router>  ->  put $out"
echo "Then on the router (system-view):  portal local-server load flash:/$(basename "$out")"

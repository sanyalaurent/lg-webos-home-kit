#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu
umask 077
HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
. "$HERE/upstream.lock"
[ "$#" = 1 ] || { echo 'Usage: fetch-upstream.sh DESTINATION_DIRECTORY' >&2; exit 2; }
mkdir -p "$1"
destination=$(CDPATH='' cd -- "$1" && pwd)
archive="$destination/zapret2-$VERSION-openwrt-embedded.tar.gz"
[ ! -e "$archive" ] || { echo 'Refusing to overwrite existing archive' >&2; exit 1; }
temporary=$(mktemp "$archive.part.XXXXXX")
trap 'rm -f "$temporary"' EXIT INT TERM
curl --proto '=https' --tlsv1.2 --fail --location --connect-timeout 10 --max-time 120 -o "$temporary" "$URL"
if command -v sha256sum >/dev/null 2>&1; then actual=$(sha256sum "$temporary"); else actual=$(shasum -a 256 "$temporary"); fi
[ "${actual%% *}" = "$SHA256" ] || { echo 'SHA256 mismatch; refusing archive' >&2; exit 1; }
mv "$temporary" "$archive"
printf 'Verified %s\nRead upstream installation instructions before extracting/installing.\n' "$archive"

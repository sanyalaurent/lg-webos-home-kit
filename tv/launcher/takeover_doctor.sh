#!/bin/sh
# Read-only, partial preflight for the pinned webOS 5/6 executable method.
# Run explicitly with: ssh HOST 'sh -s' < tv/launcher/takeover_doctor.sh
set -eu
fail() { printf '%s\n' "REFUSE: $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || fail 'root SSH is required'
[ -r /etc/starfish-release ] || fail 'webOS release file unavailable'
grep -Eq 'release [56]\.' /etc/starfish-release || fail 'this doctor covers only webOS 5/6; other boot graphs require review'
printf '%s\n' 'webOS release:'
cat /etc/starfish-release
printf 'Kernel/CPU: '; uname -sm
EXE=/usr/bin/com.webos.app.home
[ -f "$EXE" ] && [ ! -L "$EXE" ] || fail 'expected a regular LG Home executable'
set -- $(od -An -tu1 -N20 "$EXE")
[ "$#" = 20 ] || fail 'could not read ELF header'
[ "$1 $2 $3 $4 $5 $6" = '127 69 76 70 1 1' ] || fail 'LG Home is not ARM32 little-endian ELF'
shift 18
[ "$1 $2" = '40 0' ] || fail 'LG Home is not EM_ARM'
[ -x /lib/ld-linux.so.3 ] || fail 'ARM32 dynamic loader unavailable'
[ -r /proc/self/mountinfo ] || fail 'mount information unavailable'
if awk -v p="$EXE" '$5==p {found=1} END {exit !found}' /proc/self/mountinfo; then
    fail 'LG Home already has a mount; inspect and disable the previous takeover first'
fi
[ -x /usr/bin/node ] || fail 'upstream Home integration requires /usr/bin/node'
[ -d /var/lib/webosbrew/init.d ] || fail 'webosbrew boot hook directory unavailable'
[ -d /var/luna-service2 ] || fail 'early Luna service directory unavailable'
if [ -e /var/lib/luma-home/state.json ] || [ -e /var/lib/webosbrew/init.d/64-luma-home ]; then
    fail 'existing Luma takeover state requires its own status/disable review'
fi
printf '%s\n' 'Partial preflight passed. No files, mounts, services or UI were changed.'
printf '%s\n' 'This is NOT permission to enable takeover: review conflicting key hooks, backup, physical escape, watchdog and boot graph in EXPERIMENTAL-HOME.md.'

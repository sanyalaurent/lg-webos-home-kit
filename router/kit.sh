#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu
umask 077
HERE=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
. "$HERE/lib.sh"
ZAPRET=/opt/zapret2
BASE=$ZAPRET/yt-kit
CUSTOM=$ZAPRET/init.d/openwrt/custom.d
require_router() {
    [ "$(id -u)" = 0 ] && [ -f /etc/openwrt_release ] || { fail 'Run this command as root on OpenWrt'; exit 1; }
    [ -f "$ZAPRET/config" ] && [ -x /etc/init.d/zapret2 ] && [ -x "$ZAPRET/nfq2/nfqws2" ] || {
        fail 'Install pinned upstream using its canonical installer first'; exit 1;
    }
}
backup() {
    saved="/root/yt-kit-backups/$(date -u +%Y%m%dT%H%M%SZ)-$$"
    mkdir -p "$saved"
    cp -p "$ZAPRET/config" "$saved/config"
    if [ -d "$BASE" ]; then tar -czf "$saved/kit.tar.gz" -C "$ZAPRET" yt-kit; fi
    if [ -f "$CUSTOM/99-youtube-kit" ]; then cp -p "$CUSTOM/99-youtube-kit" "$saved/custom"; fi
    /etc/init.d/zapret2 enabled && echo 1 >"$saved/enabled" || echo 0 >"$saved/enabled"
    printf '%s\n' "$saved"
}
doctor() {
    [ -f /etc/openwrt_release ] || { fail 'Not OpenWrt (no changes made)'; return 1; }
    missing=0
    printf 'Architecture: '; uname -m
    printf 'Kernel: '; uname -r
    printf 'Package manager: '; if command -v apk >/dev/null 2>&1; then echo apk; elif command -v opkg >/dev/null 2>&1; then echo opkg; else echo unknown; fi
    printf 'Firmware: '; ubus call system board 2>/dev/null | jsonfilter -e '@.release.description' || true
    printf 'procd: '; command -v procd || true
    df -Pm /root | tail -1 | awk '{printf "Free storage: %s MiB\n",$4}'
    for tool in nft curl resolveip jsonfilter ubus timeout flock start-stop-daemon sha256sum; do
        command -v "$tool" >/dev/null 2>&1 || { printf 'Missing: %s\n' "$tool"; missing=1; }
    done
    [ -r /proc/net/netfilter/nfnetlink_queue ] || { echo 'NFQUEUE unavailable: check exact-kernel kmod-nft-queue'; missing=1; }
    [ -x "$ZAPRET/nfq2/nfqws2" ] || { echo 'Pinned upstream not installed'; missing=1; }
    for opt in flow_offloading flow_offloading_hw; do
        value=$(uci -q get "firewall.@defaults[0].$opt" || true)
        [ "$value" != 1 ] || { printf 'Conflict: global %s enabled; review upstream selective-offload instructions\n' "$opt"; missing=1; }
    done
    awk '/MemAvailable:/ {printf "Available RAM: %.0f MiB\n",$2/1024}' /proc/meminfo
    printf 'NFQUEUE numbers in use: '; awk '{printf "%s ",$1} END {print ""}' /proc/net/netfilter/nfnetlink_queue 2>/dev/null || :
    [ "$missing" = 0 ]
}
case "${1:-help}" in
    validate) [ "$#" = 2 ] || exit 2; read_scope "$2"; echo 'Scope valid';;
    doctor) doctor;;
    backup) require_router; backup;;
    configure)
        [ "$#" = 3 ] && [ "$3" = --apply ] || { fail 'Usage: kit.sh configure LOCAL_SCOPE.conf --apply'; exit 2; }
        read_scope "$2"; require_router; doctor
        /etc/init.d/zapret2 enabled && { fail 'Disable and stop upstream before first configuration; no service was changed'; exit 1; }
        [ ! -s /proc/net/netfilter/nfnetlink_queue ] || { fail 'Stop existing NFQUEUE users before configuring'; exit 1; }
        mkdir -p "$CUSTOM"
        for item in "$CUSTOM/"*; do
            [ ! -f "$item" ] || [ "${item##*/}" = 99-youtube-kit ] || { fail 'Review/remove other custom scripts manually first'; exit 1; }
        done
        saved=$(backup); echo "Private backup: $saved"
        mkdir -p "$BASE/profiles"
        chmod 755 "$BASE" "$BASE/profiles"
        cp "$HERE/watchdog/"* "$BASE/"
        cp "$HERE/profiles/"* "$BASE/profiles/"
        cp "$HERE/config/youtube-hosts.txt" "$BASE/youtube-hosts.txt"
        chmod 644 "$BASE/youtube-hosts.txt" "$BASE/profiles/"*
        printf "KIT_ENABLED=%s\nKIT_TARGET_IPV4S='%s'\nOPENWRT_LAN='%s'\nOPENWRT_WAN4='%s'\n" "$ENABLED" "$TARGET_IPV4S" "$LAN_NETWORKS" "$WAN_NETWORKS" >"$BASE/scope.sh"
        case "$PROFILE" in current) file=A-current.conf;; split) file=B-multisplit.conf;; altfake) file=D-altfake.conf;; esac
        ln -sf "profiles/$file" "$BASE/active.conf"
        cp "$HERE/source-filter.sh" "$CUSTOM/99-youtube-kit"
        sed '/^# BEGIN PUBLIC YOUTUBE KIT$/,/^# END PUBLIC YOUTUBE KIT$/d' "$ZAPRET/config" >"$ZAPRET/config.yt-kit.new"
        cat "$HERE/config/managed-block.conf" >>"$ZAPRET/config.yt-kit.new"
        sh -n "$ZAPRET/config.yt-kit.new"
        mv "$ZAPRET/config.yt-kit.new" "$ZAPRET/config"
        chmod 700 "$BASE/watchdog.sh"
        echo 'Configured; service and watchdog remain stopped. Follow README acceptance steps.';;
    rollback)
        [ "$#" = 3 ] && [ "$3" = --apply ] || { fail 'Usage: kit.sh rollback PRIVATE_BACKUP_DIR --apply'; exit 2; }
        require_router
        [ -f "$2/config" ] && [ -f "$2/enabled" ] || { fail 'Invalid backup'; exit 1; }
        if [ -x /etc/init.d/yt-kit-watchdog ]; then /etc/init.d/yt-kit-watchdog stop; /etc/init.d/yt-kit-watchdog disable; fi
        /etc/init.d/zapret2 stop
        nft delete table inet yt_kit_probe 2>/dev/null || :
        cp -p "$2/config" "$ZAPRET/config"
        rm -f "$CUSTOM/99-youtube-kit"
        [ ! -f "$2/custom" ] || cp -p "$2/custom" "$CUSTOM/99-youtube-kit"
        # Keep current kit files for inspection; restore previous pointer/settings if present.
        [ ! -f "$2/kit.tar.gz" ] || tar -xzf "$2/kit.tar.gz" -C "$ZAPRET"
        if [ "$(cat "$2/enabled")" = 1 ]; then /etc/init.d/zapret2 enable; /etc/init.d/zapret2 start; else /etc/init.d/zapret2 disable; fi
        echo 'Restored saved upstream config/service enable state. WAN and Wi-Fi were not changed.';;
    *) echo 'Usage: kit.sh validate FILE | doctor | backup | configure FILE --apply | rollback BACKUP --apply';;
esac

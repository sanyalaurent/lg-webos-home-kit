#!/bin/sh
# SPDX-License-Identifier: MIT
set -f
umask 077
BASE=/opt/zapret2/yt-kit
RUN=/tmp/yt-kit
mkdir -p "$RUN"
exec 9>"$RUN/lock"
flock -n 9 || exit 0
. "$BASE/scope.sh"
. "$BASE/settings.conf"
[ "$WATCHDOG_ENABLED" = 1 ] || { echo "Watchdog disabled in settings.conf"; exit 0; }
PROBE_UID=$(id -u "$PROBE_USER") || exit 2
[ "$PROBE_UID" -gt 0 ] || exit 2
CONTROL_WAN=${OPENWRT_WAN4%% *}
. "$BASE/backend.sh"
. "$BASE/controller.sh"
CURRENT_PROFILE=$(read_current) || exit 2
SLEEP_PID=
cleanup() {
    [ -z "$SLEEP_PID" ] || kill "$SLEEP_PID" 2>/dev/null || true
    stop_probe
    [ "$TRIAL_ACTIVE" != 1 ] || trial_rollback
}
trap 'exit 0' TERM INT
trap cleanup EXIT
# A killed worker may have left a RAM-only trial. Cold boot automatically uses
# the persistent known-good pointer because /tmp does not survive a reboot.
cleanup_children
if [ -f "$RUN/trial.conf" ] || [ -f "$RUN/trial.pending" ]; then
    TRIAL_ACTIVE=1
    trial_rollback || exit 1
fi
case "${1:-watch}" in
    probe)
        rm -f "$RUN/targets"
        if [ "${2:-active}" = active ]; then probe_current; else probe_candidate "$2"; fi
        result=$?
        cat "$RUN/last-probe.txt" 2>/dev/null
        printf 'result=%s detail=%s\n' "$result" "$LAST_DETAIL"
        exit "$result";;
    once)
        rm -f "$RUN/targets"
        tick
        emit_status "$STATUS" "$STATUS_DETAILS"
        cat "$RUN/status.json"
        exit 0;;
    watch) ;;
    *) exit 2;;
esac
while :; do
    CURRENT_PROFILE=$(read_current) || exit 2
    rm -f "$RUN/targets"
    tick
    emit_status "$STATUS" "$STATUS_DETAILS"
    sleep "$INTERVAL" 9>&- & SLEEP_PID=$!
    wait "$SLEEP_PID" || true
    SLEEP_PID=
done

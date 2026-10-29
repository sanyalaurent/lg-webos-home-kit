#!/bin/sh
# SPDX-License-Identifier: MIT
# Generic OpenWrt adapter. The controller owns policy; this file owns bounded probes and
# transactional changes. Only the non-login ytprobe UID enters the probe queue.
BASE=/opt/zapret2/yt-kit
ZAPRET=/opt/zapret2
RUN=/tmp/yt-kit
PROBE_PID=
CURL_PID=
TRIAL_ACTIVE=0
LAST_DETAIL=

profile_file() {
    case "$1" in
        current) echo "$BASE/profiles/A-current.conf";;
        split) echo "$BASE/profiles/B-multisplit.conf";;
        altfake) echo "$BASE/profiles/D-altfake.conf";;
        *) return 1;;
    esac
}
read_current() {
    case "$(readlink "$BASE/active.conf")" in
        profiles/A-current.conf) echo current;;
        profiles/B-multisplit.conf) echo split;;
        profiles/D-altfake.conf) echo altfake;;
        *) return 1;;
    esac
}
is_enabled() {
    [ "$WATCHDOG_ENABLED" = 1 ] && [ "$KIT_ENABLED" = 1 ] &&
        [ -x /etc/init.d/zapret2 ] && /etc/init.d/zapret2 enabled
}
uptime_seconds() { cut -d. -f1 /proc/uptime; }
pause_between_probes() { sleep "$1"; }

queue_alive() {
    local pid
    pid=$(awk -v q="$1" '$1==q {print $2}' /proc/net/netfilter/nfnetlink_queue 2>/dev/null)
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null &&
        [ "$(readlink /proc/"$pid"/exe)" = "$(readlink -f "$ZAPRET/nfq2/nfqws2")" ]
}
runtime_ok() { queue_alive 300; }
wait_queue() {
    local n=0
    while [ "$n" -lt 5 ]; do
        queue_alive "$1" && return 0
        sleep 1; n=$((n+1))
    done
    return 1
}
recover_runtime() {
    is_enabled || return 1
    timeout 25 /etc/init.d/zapret2 restart_daemons >"$RUN/restart.log" 2>&1 9>&- || return 1
    wait_queue 300
}

ensure_probe_table() {
    nft list table inet yt_kit_probe >/dev/null 2>&1 && return 0
    nft -f - <<NFT
table inet yt_kit_probe {
 chain mark_probe {
  type route hook output priority mangle; policy accept;
  meta nfproto ipv4 meta skuid $PROBE_UID tcp dport 443 meta mark & 0x40000000 == 0 meta mark set meta mark | 0x08000000
 }
 chain probe_postnat {
  type filter hook postrouting priority srcnat + 2; policy accept;
 }
}
NFT
}
select_probe_queue() {
    case "$1" in 300|301) ;; *) return 1;; esac
    ensure_probe_table || return 1
    nft -f - <<NFT
flush chain inet yt_kit_probe probe_postnat
add rule inet yt_kit_probe probe_postnat meta nfproto ipv4 meta mark & 0x08000000 != 0 meta mark & 0x40000000 == 0 tcp dport 443 ct original packets 1-20 meta mark set meta mark | 0x20000000 counter queue flags bypass to $1
NFT
}

controls_ok() {
    local up pair url expected result rc code unknown=0
    up=$(ubus call "network.interface.$CONTROL_WAN" status 2>/dev/null | jsonfilter -e '@.up')
    case "$up" in true) ;; false) LAST_DETAIL=wan_down; return 1;; *) LAST_DETAIL=wan_unknown; return 2;; esac
    for pair in 'https://www.google.com/generate_204|204' 'https://www.cloudflare.com/cdn-cgi/trace|200'; do
        url=${pair%|*}; expected=${pair##*|}
        result=$(curl -q -4 --noproxy '*' -sS -o /dev/null --connect-timeout 3 --max-time 5 \
            --max-filesize 131072 -w '%{http_code}' "$url" 2>"$RUN/control.err")
        rc=$?
        [ "$rc" = 0 ] && [ "$result" = "$expected" ] && return 0
        case "$rc" in 6|60|77) unknown=1;; esac
    done
    LAST_DETAIL=external_controls_failed
    [ "$unknown" = 0 ] || return 2
    return 1
}
prepare_targets() {
    local host ip
    [ -s "$RUN/targets" ] && return 0
    : >"$RUN/targets.new"
    for host in www.youtube.com i.ytimg.com redirector.googlevideo.com; do
        ip=$(resolveip -4 -t 3 "$host" 2>/dev/null | head -1)
        case "$ip" in ''|*[!0-9.]*) rm -f "$RUN/targets.new"; LAST_DETAIL=dns_unavailable; return 2;; esac
        printf '%s %s\n' "$host" "$ip" >>"$RUN/targets.new"
    done
    mv "$RUN/targets.new" "$RUN/targets"
}
probe_urls() {
    local host path expected minbytes ip result rc code bytes failed=0 unknown=0
    prepare_targets || return 2
    : >"$RUN/last-probe.txt"
    for item in 'www.youtube.com|/generate_204|204|0' \
        'i.ytimg.com|/vi/aqz-KE-bpKQ/hqdefault.jpg|200|1000' \
        'redirector.googlevideo.com|/generate_204|204|0'; do
        host=${item%%|*}; item=${item#*|}; path=${item%%|*}; item=${item#*|}
        expected=${item%%|*}; minbytes=${item##*|}
        ip=$(awk -v h="$host" '$1==h {print $2}' "$RUN/targets")
        # -q disables curlrc; no proxy, redirects, cookies, signed URLs or response
        # bodies are saved. Pin the same DNS snapshot for current/candidate tests.
        start-stop-daemon -S -c "$PROBE_USER" -p "$RUN/unused-curl.pid" \
            -x /usr/bin/curl -- -q -4 --noproxy '*' -sS -o /dev/null \
            --tlsv1.2 --tls-max 1.2 --http1.1 --connect-timeout 4 --max-time 8 \
            --max-filesize 131072 --resolve "$host:443:$ip" \
            -w '%{http_code} %{size_download} %{time_total}' "https://$host$path" \
            >"$RUN/curl.result" 2>"$RUN/probe.err" 9>&- &
        CURL_PID=$!
        printf '%s\n' "$CURL_PID" >"$RUN/curl.pid"
        wait "$CURL_PID"
        rc=$?
        CURL_PID=
        rm -f "$RUN/curl.pid"
        result=$(cat "$RUN/curl.result")
        printf '%s exit=%s %s\n' "$host" "$rc" "$result" >>"$RUN/last-probe.txt"
        set -- $result; code=${1:-000}; bytes=${2:-0}
        if [ "$rc" = 0 ] && [ "$code" = "$expected" ] && [ "$bytes" -ge "$minbytes" ] 2>/dev/null; then
            :
        else
            case "$rc" in
                7|18|28|35|52|55|56) failed=1;;
                *) unknown=1;;
            esac
        fi
    done
    if [ "$unknown" = 1 ]; then LAST_DETAIL=endpoint_or_certificate_or_local_error; return 2; fi
    if [ "$failed" = 1 ]; then LAST_DETAIL=youtube_transport_failure; return 1; fi
    LAST_DETAIL=three_tls_probes_ok
    return 0
}
probe_current() {
    runtime_ok || { LAST_DETAIL=production_queue_missing; return 2; }
    select_probe_queue 300 || { LAST_DETAIL=probe_rules_failed; return 2; }
    checked_probe 300
}

checked_probe() {
    local before after result
    before=$(awk -v q="$1" '$1==q {print $8}' /proc/net/netfilter/nfnetlink_queue)
    probe_urls; result=$?
    after=$(awk -v q="$1" '$1==q {print $8}' /proc/net/netfilter/nfnetlink_queue)
    if ! queue_alive "$1" || [ -z "$before" ] || [ -z "$after" ] || [ "$before" = "$after" ]; then
        LAST_DETAIL=probe_did_not_traverse_live_queue
        return 2
    fi
    printf 'queue=%s sequence_before=%s sequence_after=%s\n' "$1" "$before" "$after" >>"$RUN/last-probe.txt"
    return "$result"
}

stop_probe() {
    if nft list table inet yt_kit_probe >/dev/null 2>&1; then
        select_probe_queue 300 >/dev/null 2>&1 || true
    fi
    cleanup_children
    PROBE_PID=
}
cleanup_children() {
    local pid n
    # Netlink fallback covers a kill between starting the child and writing PID.
    for pid in "$PROBE_PID" "$(cat "$RUN/candidate.pid" 2>/dev/null)" \
        "$(awk '$1==301 {print $2}' /proc/net/netfilter/nfnetlink_queue 2>/dev/null)"; do
        case "$pid" in ''|*[!0-9]*) continue;; esac
        [ "$(readlink /proc/"$pid"/exe 2>/dev/null)" = "$(readlink -f "$ZAPRET/nfq2/nfqws2")" ] || continue
        tr '\000' '\n' </proc/"$pid"/cmdline | grep -qx -- '--comment=yt-kit-probe' || continue
        kill "$pid" 2>/dev/null || true
        n=0
        while kill -0 "$pid" 2>/dev/null && [ "$n" -lt 3 ]; do sleep 1; n=$((n+1)); done
        kill -KILL "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
    pid=${CURL_PID:-$(cat "$RUN/curl.pid" 2>/dev/null)}
    case "$pid" in ''|*[!0-9]*) :;; *)
        if [ "$(awk '/^Uid:/ {print $2}' /proc/"$pid"/status 2>/dev/null)" = "$PROBE_UID" ] &&
            [ "$(readlink /proc/"$pid"/exe 2>/dev/null)" = /usr/bin/curl ]; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi;;
    esac
    rm -f "$RUN/candidate.pid" "$RUN/curl.pid"
    PROBE_PID= CURL_PID=
}
probe_candidate() {
    local file opt result
    file=$(profile_file "$1") || return 2
    queue_alive 301 && { LAST_DETAIL=probe_queue_already_in_use; return 2; }
    opt=$(. "$file"; printf '%s' "$NFQWS2_OPT" | sed \
        "s|<HOSTLIST>|--hostlist=$BASE/youtube-hosts.txt|g;s|<HOSTLIST_NOAUTO>|--hostlist=$BASE/youtube-hosts.txt|g")
    # Trusted root-owned profile tokens, split without eval or glob expansion.
    set -f
    "$ZAPRET/nfq2/nfqws2" --qnum=301 --comment=yt-kit-probe --user=daemon --fwmark=0x40000000 \
        "--lua-init=@$ZAPRET/lua/zapret-lib.lua" \
        "--lua-init=@$ZAPRET/lua/zapret-antidpi.lua" \
        "--lua-init=@$ZAPRET/lua/zapret-auto.lua" $opt >"$RUN/candidate.log" 2>&1 9>&- &
    PROBE_PID=$!
    printf '%s\n' "$PROBE_PID" >"$RUN/candidate.pid"
    if ! wait_queue 301 || ! select_probe_queue 301; then stop_probe; LAST_DETAIL=candidate_start_failed; return 2; fi
    checked_probe 301; result=$?
    stop_probe
    return "$result"
}

trial_start() {
    local file
    is_enabled || return 1
    file=$(profile_file "$1") || return 1
    : >"$RUN/trial.pending"
    TRIAL_ACTIVE=1
    cp "$file" "$RUN/trial.conf.new" && mv "$RUN/trial.conf.new" "$RUN/trial.conf" || return 1
    recover_runtime
}
trial_verify() { probe_current; }
trial_commit() {
    local file
    is_enabled || return 1
    file=$(profile_file "$1") || return 1
    rm -f "$BASE/active.conf.next"
    ln -s "profiles/${file##*/}" "$BASE/active.conf.next" || return 1
    is_enabled || { rm -f "$BASE/active.conf.next"; return 1; }
    mv -f "$BASE/active.conf.next" "$BASE/active.conf" || return 1
    rm -f "$RUN/trial.conf" "$RUN/trial.pending"
    TRIAL_ACTIVE=0
    logger -t yt-kit "Accepted tested profile: $1" || true
    return 0
}
trial_rollback() {
    rm -f "$RUN/trial.conf" "$RUN/trial.conf.new"
    # An explicit service disable must never be undone by watchdog cleanup.
    if is_enabled; then recover_runtime || return 1; fi
    rm -f "$RUN/trial.pending"
    TRIAL_ACTIVE=0
    return 0
}

emit_status() {
    local status="$1" detail="$2" now old
    now=$(date +%s)
    old=$(cat "$RUN/last-status" 2>/dev/null)
    [ "$old" = "$status" ] || logger -t yt-kit "$status profile=$CURRENT_PROFILE $detail"
    printf '%s\n' "$status" >"$RUN/last-status"
    # Status/detail are controller-owned fixed strings, never server responses.
    printf '{"status":"%s","profile":"%s","failures":%s,"checked_at":%s,"detail":"%s","probe_detail":"%s"}\n' \
        "$status" "$CURRENT_PROFILE" "${FAILURES:-0}" "$now" "$detail" "$LAST_DETAIL" >"$RUN/status.json.new"
    mv "$RUN/status.json.new" "$RUN/status.json"
}

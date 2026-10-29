#!/bin/sh
# SPDX-License-Identifier: MIT
fail() { printf '%s\n' "$*" >&2; return 1; }
ipv4_host() {
    case "$1" in */32) ip=${1%/32};; *) return 1;; esac
    printf '%s\n' "$ip" | awk -F. 'NF!=4 {exit 1} {for(i=1;i<=4;i++) if($i !~ /^[0-9]+$/ || $i>255 || (length($i)>1 && substr($i,1,1)=="0")) exit 1; if($1==0 || $1==127 || $1>=224) exit 1}'
}
read_scope() {
    case "$-" in *f*) scope_had_noglob=1;; *) scope_had_noglob=0;; esac
    set -f
    ENABLED=0 TARGET_IPV4S= LAN_NETWORKS= WAN_NETWORKS= PROFILE=current
    while IFS='=' read -r key value || [ -n "$key" ]; do
        case "$key" in ''|'#'*) continue;; esac
        case "$key" in
            ENABLED) ENABLED=$value;; TARGET_IPV4S) TARGET_IPV4S=$value;;
            LAN_NETWORKS) LAN_NETWORKS=$value;; WAN_NETWORKS) WAN_NETWORKS=$value;;
            PROFILE) PROFILE=$value;; *) fail "Unknown setting: $key"; return 1;;
        esac
    done < "$1"
    case "$ENABLED" in 0|1) ;; *) fail 'ENABLED must be 0 or 1'; return 1;; esac
    case "$PROFILE" in current|split|altfake) ;; *) fail 'Unknown PROFILE'; return 1;; esac
    for ip in $TARGET_IPV4S; do ipv4_host "$ip" || { fail 'Use individual IPv4 /32 addresses only'; return 1; }; done
    for net in $LAN_NETWORKS $WAN_NETWORKS; do
        case "$net" in ''|*[!a-zA-Z0-9_-]*) fail 'Invalid netifd network name'; return 1;; esac
    done
    if [ "$ENABLED" = 1 ]; then
        [ -n "$TARGET_IPV4S" ] && [ -n "$LAN_NETWORKS" ] && [ -n "$WAN_NETWORKS" ] || {
            fail 'Enabled scope needs targets, LAN_NETWORKS and WAN_NETWORKS'; return 1;
        }
    fi
    [ "$scope_had_noglob" = 1 ] || set +f
}

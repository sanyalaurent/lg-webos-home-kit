#!/bin/sh /etc/rc.common
# SPDX-License-Identifier: MIT
USE_PROCD=1
START=99
STOP=10
start_service() {
    procd_open_instance
    procd_set_param command /opt/zapret2/yt-kit/watchdog.sh watch
    procd_set_param respawn 3600 5 5
    procd_set_param term_timeout 45
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}
stop_service() {
    nft delete table inet yt_kit_probe 2>/dev/null || :
}

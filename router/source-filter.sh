#!/bin/sh
# SPDX-License-Identifier: MIT
# Own integration code using the public upstream custom-hook interface.
# Empty targets never fall back to an entire private subnet.
zapret_custom_firewall_nft() {
    nft_add_chain ytkit_sources 'type filter hook forward priority mangle;' || return 1
    nft_flush_chain ytkit_sources || return 1
    [ "$KIT_ENABLED" = 1 ] && [ -n "$KIT_TARGET_IPV4S" ] || return 0
    local addresses='' address
    for address in $KIT_TARGET_IPV4S; do addresses="${addresses:+$addresses,}$address"; done
    nft_create_set ytkit_sources 'type ipv4_addr; flags interval; auto-merge;' || return 1
    nft_flush_set ytkit_sources || return 1
    nft_add_set_element ytkit_sources "$addresses" || return 1
    nft_add_rule ytkit_sources iifname @lanif ip saddr @ytkit_sources meta mark set meta mark or 0x10000000
}
zapret_custom_firewall_nft_flush() {
    nft_flush_chain ytkit_sources 2>/dev/null || :
    nft_del_chain ytkit_sources 2>/dev/null || :
    nft delete set inet "$ZAPRET_NFT_TABLE" ytkit_sources 2>/dev/null || :
}

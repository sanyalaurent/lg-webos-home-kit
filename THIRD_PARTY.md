# Upstream projects and licenses

This repository contains its own integration scripts, examples and documentation.
The root MIT license covers those files. It does not relicense downloaded software,
LG application files, icons, firmware, or the dependencies of the projects below.
Upstream source trees, firmware and application binaries are not committed here.

| Project | Purpose | Source |
|---|---|---|
| zapret | Original DPI bypass project; useful background and platform documentation | [bol-van/zapret](https://github.com/bol-van/zapret) |
| zapret2 | Linux NFQUEUE engine and OpenWrt integration used by the router module | [bol-van/zapret2](https://github.com/bol-van/zapret2) |
| zapret-discord-youtube | Windows alternative; BAT/WinDivert tools are not router firmware packages | [Flowseal/zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube) |
| YouTube webOS Cobalt AdFree | Separate native client used by the optional TV module | [RF1705/youtube-webos-cobalt-adfree](https://github.com/RF1705/youtube-webos-cobalt-adfree) |
| Cobalt | Browser/runtime used by the upstream TV client | [youtube/cobalt](https://github.com/youtube/cobalt) |
| OpenWrt | Supported automation platform for the supplied router scripts | [openwrt.org](https://openwrt.org/) |

The pinned zapret2 release is `v1.0.6`; its MIT license is in
[docs/LICENSE.txt](https://github.com/bol-van/zapret2/blob/v1.0.6/docs/LICENSE.txt).
Its bundled dependencies may have additional licenses. The RF client is pinned to
`v2.0.6-beta`; retain the license notices supplied with that application and Cobalt.
Its release is a beta, not a certification of support for every LG television.

Downloaders verify pinned SHA-256 digests before unpacking. Changing a version
requires reviewing the release, its licenses and the updated digest together.
There is no automatic download of an unreviewed `latest` binary.

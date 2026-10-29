# OpenWrt module

This module is for **OpenWrt with fw4/nftables and procd**, after a compatible
upstream zapret2 installation. It is not an installer for arbitrary stock-router
firmware. Give the repository and your exact router model, hardware revision,
firmware, architecture and kernel to your assistant first. An unsupported router
can instead use a separate compatible gateway. Nothing here flashes firmware,
changes WAN credentials, configures Wi-Fi, opens WAN SSH or installs TV software.

zapret2 addresses network DPI interference; it **does not remove YouTube ads**.
See the TV module for application-level ad filtering.

## Where to run commands

`router/` is copied from this repository to **your OpenWrt router**. Run `kit.sh`,
upstream installation/package-manager commands, and watchdog/service commands
**on that router as root**, not in your Mac/Windows/Linux computer's shell.
The download-only `fetch-upstream.sh` can run on a computer with curl and a SHA256
utility; it does not install anything there.

From a terminal on your computer, in the repository root:

```sh
scp -r router root@ROUTER_HOST:/tmp/youtube-kit-router
ssh root@ROUTER_HOST 'sh /tmp/youtube-kit-router/kit.sh doctor'
ssh root@ROUTER_HOST
```

Replace `ROUTER_HOST` with your router's address or existing SSH alias. Keep normal
SSH host-key verification enabled and verify the host fingerprint. If the router
has no SFTP server and your OpenSSH `scp` defaults to SFTP, use `scp -O -r` for that
copy instead; no extra server is required. Do not put passwords in commands.

In the router's SSH shell, use `cd /tmp/youtube-kit-router`. All `./kit.sh` and
`./config/` examples below assume that directory. Your private edited scope and
backups live outside both this copied module and the public repository. `/tmp`
is temporary; retain a copy of this module on your computer for future rollback.

## Compatibility and upstream first

Use the original [zapret2 documentation](https://github.com/bol-van/zapret2/tree/v1.0.6)
and its OpenWrt installer. This kit pins `v1.0.6`; see `upstream.lock` for the exact
release archive and SHA256. The original [zapret](https://github.com/bol-van/zapret)
is a separate upstream project, not an interchangeable config format. Windows
bundles such as Flowseal are not router installers.

```sh
sh router/fetch-upstream.sh /path/to/private/upstream-download
```

This only downloads and verifies the archive. Read the included upstream docs,
select the proper architecture using its installer, and review its firewall and
offload changes. Install under `/opt/zapret2`. The upstream source, binaries and
licenses remain separate; this repository does not vendor them. Upstream's own
project license is MIT; bundled third-party components have their own licenses.

Use the package manager supplied by your firmware: `apk update` / `apk add` on
apk releases, or `opkg update` / `opkg install` on opkg releases. Do not mix feeds
or use `--force-depends`. Kernel modules must match the **exact running kernel**.
If matching packages are unavailable, stop and assess compatibility; this kit
does not solve that by flashing or upgrading firmware.

Relevant dependencies are `nftables`, `kmod-nft-queue`, `kmod-nft-nat`,
`kmod-nft-offload` (selective software offload), `curl` with CA certificates,
`resolveip`, `jsonfilter`, `ubus`, `flock`, `timeout` and `start-stop-daemon`.
Package names can vary by release; ask the package manager which package provides
the missing command. A working upstream architecture-specific `nfq2/nfqws2` and
the upstream Lua files are also required. TLS verification stays enabled.

```sh
sh ./kit.sh doctor
```

`doctor` is read-only: it reports firmware, architecture, kernel, package manager,
procd, free storage/RAM, missing tools, NFQUEUE presence/numbers and conflicting
global offload settings. It does not prove board support, speed, streaming,
strategy effectiveness, or absence of mark/queue conflicts. Queues 300/301 and
mark bits `0x10000000`, `0x20000000`, `0x40000000`, `0x08000000` must be available.
Review existing nft policies before using them. Global fw4 offload must already be
disabled according to upstream instructions, so upstream can apply selective
software offload. This kit does not change UCI firewall defaults itself.

## Explicit device scope and stopped configuration

Keep your edited file **outside the public repository**. The file is plain
`KEY=value` data, not shell; no quotes or inline comments. The shipped example is
disabled with no devices or inferred interfaces. Targets are individual IPv4
`/32` addresses only; broad subnets and IPv6 are rejected. Documentation addresses
`192.0.2.10/32 192.0.2.11/32` are TEST-NET examples, not working LAN addresses.
Enter your own device IPs and actual **netifd network names**, not guessed Linux
device names. Reserve those addresses in your existing DHCP administration UI.
This kit does not edit DHCP or collect MAC addresses.

```sh
cp ./config/devices.example.conf /root/my-youtube-scope.conf
# Edit /root/my-youtube-scope.conf on your router.
sh ./kit.sh validate /root/my-youtube-scope.conf
sh ./kit.sh backup
```

For first configuration, explicitly stop and disable the upstream service after
reviewing how it affects any existing installation. The configure command refuses
an enabled service, active NFQUEUE users and other upstream custom scripts.

```sh
/etc/init.d/zapret2 stop
/etc/init.d/zapret2 disable
sh ./kit.sh configure /root/my-youtube-scope.conf --apply
```

`configure` saves a private timestamped backup under `/root/yt-kit-backups/`,
copies own integration files, appends a marked override to upstream config, and
installs an own source-marking hook. It **does not start or enable** either service.
The source set never defaults to an entire LAN when empty. The fixed hostlist is
only YouTube-related domains; interception is IPv4 outgoing TLS/QUIC on port 443,
first 20 TCP / 5 UDP original-direction packets, no incoming interception.
Other destinations and devices remain outside the selected processing scope.
No DNS replacement, WAN, Wi-Fi or router-administration settings are changed.

Set `ENABLED=1` in your private scope only after entering targets/interfaces;
configure again while stopped, then start upstream manually. Do not enable boot
startup until manual acceptance succeeds:

```sh
/etc/init.d/zapret2 start
# Check new connections from an allowed device, then an excluded device.
# Test YouTube login, thumbnails, seeking and several actual videos/formats.
# Only after acceptance:
/etc/init.d/zapret2 enable
```

The example strategies are candidates, not universal provider recipes. `current`
means the initial example profile, not a claim of a working local baseline.
Already established/offloaded TCP or QUIC flows may retain old behavior: reconnect
the application for a fresh handshake. Do not flush all conntrack or restart
Wi-Fi just to test a target change. IPv6 is outside this module; dual-stack
clients can take an unprocessed IPv6 path.

## Optional bounded strategy watchdog

Installed under `/opt/zapret2/yt-kit`, disabled by default; candidate list is empty.
Create a dedicated non-login, non-root probe user using the commands supported by
your firmware (`adduser` options vary), and set `PROBE_USER` in its `settings.conf`.
Do not reuse an account that runs other applications. Its numeric UID is resolved
at startup; no fixed UID or CPU architecture is assumed. The user needs read
access to the public hostlist (installed 0644 under a 0755 directory).

Set `WATCHDOG_ENABLED=1` only when upstream already works. Run explicit isolated
checks for each strategy before adding its name to `CANDIDATES`:

```sh
/opt/zapret2/yt-kit/watchdog.sh probe active
/opt/zapret2/yt-kit/watchdog.sh probe split
/opt/zapret2/yt-kit/watchdog.sh probe altfake
```

These probe commands create only the monitor's `inet yt_kit_probe` table and an
isolated queue-301 candidate process; they do not adopt a production profile.
Only the dedicated probe user's IPv4 TCP/443 traffic is redirected. They verify
queue traversal and known public HTTPS fronts: YouTube 204, a public thumbnail,
and googlevideo 204. Control endpoints independently check general connectivity.
They are **not a video-stream, QUIC, codec, account or DRM proof**. A green result
cannot guarantee playback. Validate real playback yourself before enabling any
automatic strategy changes. The dedicated probes use TLS 1.2 / HTTP/1.1 so results
remain comparable; they do not cover the TV's every transport variation.

The controller requires three consecutive definite failures, 180-second boot
grace, healthy controls, a repeat of the current profile, two isolated candidate
passes separated by three seconds, another current-profile check, then two
production checks. Only after success does it atomically change `active.conf`.
Failed trials roll back; failed rollback blocks further changes. DNS, certificate,
unexpected HTTP/service responses are indeterminate and reset the failure streak.
An outage or disabled upstream never triggers profile adoption. Runtime repair
has its own 30-minute cooldown and never flips a profile in the same tick.
Daemon restarts are timeout-bounded; changes use a RAM trial so reboot returns to
the last committed profile. Interrupted RAM trials are rolled back on next start.

After testing, optionally install the procd wrapper:

```sh
cp /opt/zapret2/yt-kit/init.sh /etc/init.d/yt-kit-watchdog
chmod 755 /etc/init.d/yt-kit-watchdog
/etc/init.d/yt-kit-watchdog start
# Inspect /tmp/yt-kit/status.json and then enable if accepted:
/etc/init.d/yt-kit-watchdog enable
```

Status logs record fixed states and profile names, never cookies, signed video
URLs, user traffic bodies or account credentials. Runtime `/tmp` files are
private. Disabling the monitor does not disable upstream; disabling upstream
prevents the monitor from restarting it. Leave `CANDIDATES=''` for monitoring and
bounded daemon repair without automatic strategy adoption.

## Rollback and validation limits

```sh
sh ./kit.sh rollback /root/yt-kit-backups/YOUR_BACKUP --apply
```

Rollback stops/disables this monitor, stops upstream, removes its probe table,
restores the saved config/custom hook and prior kit state when present, then
restores upstream's saved enable state. Keep the matching kit code available for
rollback. It leaves integration files for inspection and does not delete upstream
packages, change WAN/Wi-Fi or reset your router. Private backups and edited scopes
must never be committed or uploaded.

Local checks: `python3 -m unittest discover -s router/tests -v` plus `sh -n` on
shell files. Tests execute the real controller with deterministic mock operations
and configure/copy/rollback in a relocated fixture filesystem. They do not prove
hardware compatibility, firmware behavior, current censorship bypass or streaming
acceptance on an arbitrary router. No universal speed claim is made.

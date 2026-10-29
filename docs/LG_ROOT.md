# Root access on an LG webOS TV

This is a compatibility-first guide for a TV you own. Root is distinct from
[official Developer Mode](LG_DEVELOPER_MODE.md): `prisoner` on port 9922 is a
restricted development account; root must be demonstrated by `uid=0` in the
actual command-execution context. Installing Homebrew Channel alone does not
prove that its service has root or that root survives reboot.

This repository does not ship an exploit or promise a universal rooting method.
Use the chosen project's original instructions and reviewed, pinned upstream
source. Do not run copied exploits from a chat attachment or pipe a mutable URL
straight into a shell.

## 1. Establish compatibility before changing anything

1. Record the **full model suffix, board/SoC if available, installed firmware
   build and numeric webOS/SDK version**, plus whether Developer Mode or an older
   root method is already present. The official CLI diagnostics are in the
   [Developer Mode guide](LG_DEVELOPER_MODE.md#5-perform-read-only-acceptance).
2. Check [CanI.RootMy.TV](https://cani.rootmy.tv/) and the chosen exploit's current
   README/issues. A database result or a report for the same model with another
   firmware is useful evidence, not a compatibility guarantee. New methods may
   appear before the database is updated.
3. Choose a method for that exact installed build. Do not update, downgrade or
   factory-reset blindly to match an old tutorial. Updates can patch both the
   exploit and persistence; their behavior must be assessed separately.
4. Read the method's recovery and Developer Mode requirements before starting.
   Keep the physical remote, local display and a way to regain network access.
   Store any app/settings backups privately outside this repository. Do not
   export or upload account databases, keys or complete unredacted TV logs.

Useful primary/community starting points:

| Method | Selection rule |
| --- | --- |
| [SlopBro](https://github.com/throwaway96/slopbro) | Its author reports use on webOS 4–11 and documents a service-path workaround. That version range is not an assurance for every firmware. Check current failures and success reports. |
| [DejaVuln autoroot](https://github.com/throwaway96/dejavuln-autoroot) | SlopBro's author recommends it for webOS 3.5/4.x where vulnerable. Follow its own USB procedure and exact compatibility notes. |
| [RootMyTV](https://github.com/RootMyTV/RootMyTV.github.io) | An older chain, patched on later firmware; a model's age alone does not make it applicable. Its Developer Mode requirement differs from other methods. |
| [Other documented methods](https://www.webosbrew.org/rooting/) | Use their current original guides. The community [exploit history](https://www.webosbrew.org/rooting/exploits/) explains that fixes can arrive via firmware, apps or jail configuration. Hardware modification is not an automatic software fallback. |

## 2. Example: acquire and review a pinned SlopBro revision

These commands run **on your computer**, in a private working directory outside
this public repository. They only acquire/read source until the final execution
command. Python 3 and Git are needed; SlopBro's launcher uses the standard library.

```sh
git clone --no-checkout https://github.com/throwaway96/slopbro.git slopbro-review
git -C slopbro-review checkout --detach 21023d56ca424607bb03d2939609cc658c655fc7
git -C slopbro-review rev-parse HEAD
```

The last command must print the selected full commit ID. This pinned revision
documents the commands below; it is a reproducible review point, **not a promise
that it supports your TV today**. Read its `README.md`, `slopbro.py`,
`wwwroot/main.js` and `wwwroot/autoroot.sh`, including downloads and persistence.
If your build needs a newer revision, review that revision, record its full ID,
and use its matching commands instead. Verify publisher hashes/signatures for
release downloads when provided; do not invent a checksum from a different asset.

```sh
cd slopbro-review
python3 slopbro.py --help
python3 slopbro.py --test-server simple TV_HOST
```

Replace `TV_HOST` with your TV's own LAN address. The `simple` test only serves a
connectivity response: use the printed URL in the TV browser, then stop the
server with Ctrl+C. It does not pair or launch an exploit. Both directions of
LAN connectivity must work; if needed, allow this local Python server on the
trusted LAN instead of disabling the computer's firewall globally.

**Only after choosing this method for your exact firmware**, run its documented
rooting command from the same private folder:

```sh
python3 slopbro.py TV_HOST
```

Accept the pairing prompt **on your own TV** and follow its displayed result.
The launcher saves a `.key` pairing credential locally; keep the entire working
folder out of this public repository. `--local-ip COMPUTER_LAN_IP` is available
if interface detection is wrong. `--webos-version WEBOS_MAJOR` limits target apps
by numeric major version; a newer marketing year label is not that number.
Do not add `--curl-insecure` as a default fix; correct clock/CA/connectivity issues
and consult upstream first. Source: the [pinned SlopBro README](https://github.com/throwaway96/slopbro/blob/21023d56ca424607bb03d2939609cc658c655fc7/README.md).

## 3. Verify root and respect the Developer Mode removal order

SlopBro's payload installs Homebrew Channel and attempts persistence. A success
message is the start of acceptance, not the end. Confirm Homebrew Channel's root
status and obtain an actual `id` result using a root execution channel. If an
existing root shell is available, simply run `id` there.

For **Homebrew Channel 0.7.3**, its documented root execution service accepts a
`command` field. If the Developer Mode connection still exists, this read-only
probe can demonstrate the service identity from your computer:

```sh
ares-novacom --device lgtv --run "/usr/bin/luna-send-pub -n 1 luna://org.webosbrew.hbchannel.service/exec '{\"command\":\"id\"}'"
```

Inspect `returnValue` and `stdoutString`: the latter must contain `uid=0`.
An empty response, access denial or only a `prisoner` shell is **not proof**.
Use your installed HBC version's supported diagnostics if this route is
unavailable; do not create broad LS2 roles to make the test pass.
Source: [HBC v0.7.3 exec implementation](https://github.com/webosbrew/webos-homebrew-channel/blob/v0.7.3/services/service.ts).

**Do not perform a persistence-test reboot while a conflicting Developer Mode
app remains installed.** SlopBro at the pinned revision checks the app and tells
you to uninstall it before reboot; it does not silently uninstall it for you.
After confirming its root service and preparing the selected recovery/SSH path,
remove LG's Developer Mode app through the TV UI when instructed, before that
reboot. Do not reinstall it while this root method is active.
See [SlopBro's actual post-install checks](https://github.com/throwaway96/slopbro/blob/21023d56ca424607bb03d2939609cc658c655fc7/wwwroot/autoroot.sh).

Requirements are method-specific: [RootMyTV requires removal before rooting](https://github.com/RootMyTV/RootMyTV.github.io#usage),
whereas [DejaVuln requires removal before reboot after its completion](https://github.com/throwaway96/dejavuln-autoroot#usage).
Do not combine those sequences or delete LG's internal devmode preference paths
by hand because an old tutorial did so.

## 4. Establish secure LAN SSH before relying on remote access

Use the SSH feature provided by your installed HBC/root method. Standard HBC
root SSH uses port **22**, a separate endpoint from the old `prisoner:9922` alias.
Keep it LAN-only; do not add port forwarding, WAN exposure or disable SSH host-key
checking. The private client key never goes onto the TV.

On your computer, create a dedicated key, choosing its passphrase interactively:

```sh
ssh-keygen -t ed25519 -f ~/.ssh/lg-webos -C lg-webos
```

From the **already verified root channel**, append only the public `.pub` key to
the canonical HBC v0.7.3 path `/home/root/.ssh/authorized_keys`, preserving any
existing authorized keys. This is the system account's documented path, not a
personal client directory. Do not infer it solely from `$HOME`: a root process
can inherit the development account's environment. Check the installed HBC
version's startup code before using a different path. Use
directory mode `0700`, file mode `0600`, owner root. Enable HBC SSH and disable
ordinary unauthenticated Telnet according to that installed version's settings.
Do not publish a default password or depend on one for unattended access.

Before ending the setup session, test a second connection with normal host-key
verification from your computer:

```sh
ssh -i ~/.ssh/lg-webos -o IdentitiesOnly=yes root@TV_HOST 'id'
```

Confirm `uid=0`. A successful key login alone does not prove the server has
disabled password authentication: check the selected HBC version's configuration
and advertised authentication methods. HBC v0.7.3 changes its default-password
handling when authorized keys exist, and can open an emergency Telnet service in
failsafe mode. Do not remove that recovery mechanism or erase its flag to hide an
unresolved boot failure. Sources: [HBC README](https://github.com/webosbrew/webos-homebrew-channel/tree/v0.7.3),
[HBC startup code](https://github.com/webosbrew/webos-homebrew-channel/blob/v0.7.3/services/startup.sh).

## 5. Accept persistence and keep a recovery path

1. Only after the method's Developer Mode cleanup and SSH preparation, perform
   the reboot required by its original instructions with the remote available.
2. Reconnect to the root SSH endpoint and run `id` again. Check HBC root status,
   normal TV navigation, network and ordinary app playback.
3. A remote-control wake with Quick Start+ can resume an existing system; it is
   not proof that boot persistence works. When appropriate for the chosen method,
   test a full restart separately and record the result privately.
4. Install the TV module or other customizations only after root acceptance.
   Begin with reversible app-level changes, one at a time; retain their rollback
   command and original app backups. Root itself does not speed up menus.

If a stage fails, stop repeated attempts and inspect that attempt's bounded,
redacted logs against its pinned upstream guide. Do not overwrite `kernel`,
`rootfs`, `tvservice` or other system partitions, flash another model's firmware,
or treat factory reset as a universal rescue command. Recovery/unrooting is
specific to the selected method and can erase user data; the TV module's rollback
only reverses that module, not the rooting procedure.
See the community [root warnings](https://rootmy.tv/warning).

This guide was source-checked on 2026-10-30. It does not certify an arbitrary LG
model/firmware, guarantee persistence through future updates, or contain any
owner's addresses, credentials, account data or backups.

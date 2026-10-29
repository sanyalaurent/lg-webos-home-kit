# Connect an LG webOS TV using official Developer Mode

Developer Mode provides a limited development account. It does **not** grant
root or unlock system partitions. Use this route first when you only need app
testing. If your TV is already rooted, use [the root guide](LG_ROOT.md) instead:
several community persistence methods conflict with LG's Developer Mode app.

All terminal commands below run **on your computer**, not on the router or in
the TV browser. `TV_HOST` means your own TV's LAN address; `lgtv` is only a local
CLI alias. Never substitute someone else's address or publish your local device
configuration, LG password, passphrase or downloaded SSH key.

## 1. Record the TV and prepare the network

1. In the TV's normal Settings, record its full model suffix, software/firmware
   version and webOS version. Menu names vary by generation; look under Support
   or General → TV Information/About This TV. A marketing name such as "webOS 25"
   is not interchangeable with the firmware build or SDK version.
2. Connect the computer and TV to the same trusted home LAN. A guest network or
   AP/client isolation can prevent communication even when the SSID looks similar.
   Read the TV address from its network settings or your router's client list.
3. Create/sign in to an LG Developer account on the
   [LG webOS TV Developer site](https://webostv.developer.lge.com/).
   Credentials stay with LG and the TV; this repository does not need them.

LG documents the network/account requirements and TV-side steps in
[App Testing with Developer Mode App](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app).

## 2. Check Node.js, npm and the official CLI

```sh
node --version
npm --version
npm list -g --depth=0
npm view @webos-tools/cli version engines
```

If Node/npm are missing, install a currently supported LTS from
[Node.js](https://nodejs.org/en/download), then reopen the terminal. Check the
package's current engine requirement before choosing a runtime. At the guide's
2026-10-30 verification, official CLI `3.2.6` requires Node `>=20.0.0` in its
[npm metadata](https://registry.npmjs.org/@webos-tools%2fcli/latest).
LG's installation page still lists older recommended Node versions; do not
install an end-of-life runtime solely to reproduce that old recommendation.

Install missing CLI tools from the official package:

```sh
npm install -g @webos-tools/cli
ares -V
ares-setup-device --help
```

Follow [LG's CLI installation instructions](https://webostv.developer.lge.com/develop/tools/cli-installation)
if an older webOS TV/OSE CLI conflicts with the commands. For npm permission
errors, use a user-managed Node installation or npm prefix as documented there;
do not solve this by making system directories world-writable. No TV changes
have occurred at this stage.

## 3. Enable Developer Mode on the TV

1. On the TV, open LG Apps/LG Content Store and install **Developer Mode**.
2. Open it and sign in using your LG Developer account.
3. Enable **Dev Mode Status**. Allow the TV's requested reboot.
4. Open Developer Mode again, confirm it is enabled, then enable **Key Server**.
   Keep its displayed passphrase available privately for the next step.

These are LG's official steps, not a root exploit. Do not follow them on an
already-rooted TV whose persistence instructions prohibit the app.

## 4. Register the TV and retrieve its key

```sh
ares-setup-device --list
ares-setup-device --add lgtv -i "host=TV_HOST" -i "port=9922" -i "username=prisoner"
ares-novacom --device lgtv --getkey
```

Replace `TV_HOST` before running the add command. If `lgtv` already exists,
inspect it and use `--modify lgtv` rather than overwriting an unrelated entry.
Enter the TV's passphrase **at the interactive prompt**. It is not the LG account
password, and does not belong in command arguments, shell history or this repo.
The key and local alias are stored by the CLI in your computer's private user
configuration. Key Server is for key retrieval and need not remain on afterwards.
LG does not require a separate SSH password for this account.

Command syntax and the `prisoner`/9922 connection are documented by
[LG's CLI guide](https://webostv.developer.lge.com/develop/tools/cli-dev-guide).
Do not disable SSH host-key checks or expose this port through your router.

## 5. Perform read-only acceptance

```sh
ares-device --device lgtv --system-info
ares-novacom --device lgtv --run "id"
ares-novacom --device lgtv --run "uname -r"
ares-novacom --device lgtv --run "cat /etc/palm/webos-release"
```

Record the reported model/board, firmware, SDK/webOS version and user privately.
Missing fields or permission errors mean **unknown**, not zero or root access.
The expected identity is the restricted `prisoner` account, not `uid=0`.
Its shell runs in LG's development sandbox; it can be useful for app diagnostics
but does not imply access to system settings, private Luna APIs or other apps'
data. An app installation, firmware change or root attempt is a separate step.

## 6. Keep the development session valid

Check **Remaining Session** in the Developer Mode app and use its **EXTEND**
control before expiration. The community documents a 1000-hour session; the TV's
actual displayed timer is the relevant value. LG also documents deactivation
after session expiry and after ten offline reboots. When Developer Mode is
disabled, its installed development apps are removed. Do not rely on them as an
unattended permanent installation.
Sources: [LG session behavior](https://webostv.developer.lge.com/develop/getting-started/developer-mode-app),
[webOS Homebrew Developer Mode notes](https://www.webosbrew.org/devmode/).

If connection fails, recheck the current address, session, Key Server and network
isolation first. A failed key retrieval is not evidence that the TV needs root,
a factory reset, disabled TLS verification or a different firmware.

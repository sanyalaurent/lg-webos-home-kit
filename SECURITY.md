# Privacy and reporting

Do not publish router backups, full configuration exports, `.starboard*.storage`,
YouTube profiles, cookies, SSH keys, Wi-Fi passwords, device serial numbers or MACs.
The `.gitignore` rules are a convenience; they do not make `git add -f` safe.

Store local config under `.local/` with `umask 077`; use a private staging directory
outside the repository for downloaded packages, as required by the TV downloader.
Keep root backups on the device or in a separate private directory. A SHA-256 of
a private backup is also unnecessary public metadata; publish only upstream asset digests.

For a public bug report, share the model/revision, firmware/kernel/architecture,
module version and a short sanitized error. Review diagnostics before attaching them.
Do not send a full `uci export`, `sysupgrade` archive, memory dump or RF debug log.

Run `make check` before a commit. The publication gate detects common accidental
private data and binary exports. It cannot recognize every secret or replace manual review.
If a secret has entered Git history, remove the public exposure and revoke the secret;
deleting the file from the newest commit is insufficient.

For a security issue, use a private report to the repository maintainer. If private
reporting is unavailable, open an issue asking for a private channel without posting
the exploit, credentials or device data. This kit does not provide a hosted service
or collect telemetry.

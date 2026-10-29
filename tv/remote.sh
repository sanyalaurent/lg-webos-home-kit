#!/bin/sh
# Own integration only. No upstream program is executed during staging.
set -eu
umask 077
STATE=/var/lib/youtube-kit
APP_ID=youtube.leanback.v4
ELF_SHA=15c0e77d0315a0a1ae2661100738aa191504e1f7a0ff14e2225e6553264a72a2
MOUNTINFO=/proc/self/mountinfo

die() { echo "youtube-kit: $*" >&2; exit 1; }
sha() { sha256sum "$1" | awk '{print $1}'; }

validate_metadata() {
    case "$APP" in
        /media/cryptofs/apps/usr/palm/applications/youtube.leanback.v4|/media/developer/apps/usr/palm/applications/youtube.leanback.v4) ;;
        *) die "Unsupported application path" ;;
    esac
    [ -d "$APP" ] && [ ! -L "$APP" ] || die "Application must be a real directory"
    [ -f "$APP/appinfo.json" ] && [ ! -L "$APP/appinfo.json" ] || die "Missing regular appinfo.json"
}

validate_app() {
    validate_metadata
    [ -f "$APP/cobalt" ] && [ ! -L "$APP/cobalt" ] || die "Missing regular Cobalt entrypoint"
}

release_lock() {
    rm -f "$STATE/lock/pid" "$STATE/lock/boot-id"
    rmdir "$STATE/lock" 2>/dev/null || :
}

acquire_lock() {
    boot_id=$(cat /proc/sys/kernel/random/boot_id)
    if ! mkdir "$STATE/lock" 2>/dev/null; then
        [ -f "$STATE/lock/pid" ] && [ -f "$STATE/lock/boot-id" ] || die "Incomplete lock; manual review required"
        lock_pid=$(cat "$STATE/lock/pid")
        case "$lock_pid" in *[!0-9]*|'') die "Invalid lock owner" ;; esac
        if [ "$(cat "$STATE/lock/boot-id")" = "$boot_id" ] && kill -0 "$lock_pid" 2>/dev/null; then
            die "Another operation is active"
        fi
        release_lock
        mkdir "$STATE/lock" 2>/dev/null || die "Could not acquire recovery lock"
    fi
    printf '%s\n' "$boot_id" > "$STATE/lock/boot-id"
    printf '%s\n' "$$" > "$STATE/lock/pid"
}

journal_pending() {
    printf '%s\n' "$INSTALL_ID" > "$STATE/PENDING.tmp"
    mv "$STATE/PENDING.tmp" "$STATE/PENDING"
    sync
}

choose_app() {
    APP=$1
    if [ -z "$APP" ]; then
        count=0
        for candidate in /media/cryptofs/apps/usr/palm/applications/youtube.leanback.v4 /media/developer/apps/usr/palm/applications/youtube.leanback.v4; do
            if [ -f "$candidate/appinfo.json" ]; then APP=$candidate; count=$((count + 1)); fi
        done
        [ "$count" = 1 ] || die "Specify --app-dir: none or multiple application directories found"
    fi
    validate_app
}

app_pids() {
    for process in /proc/[0-9]*; do
        [ -r "$process/status" ] || continue
        executable=$(readlink "$process/exe" 2>/dev/null || true)
        case "$executable" in
            "$APP/cobalt"|"$APP/cobalt.real"|"/var/palm/jail/$APP_ID$APP/cobalt"|"/var/palm/jail/$APP_ID$APP/cobalt.real")
                echo "${process##*/}" ;;
            "$APP/cobalt (deleted)"|"$APP/cobalt.real (deleted)"|"/var/palm/jail/$APP_ID$APP/cobalt (deleted)"|"/var/palm/jail/$APP_ID$APP/cobalt.real (deleted)")
                echo "${process##*/}" ;;
        esac
    done
}

stop_app() {
    pids=$(app_pids)
    for pid in $pids; do kill -TERM "$pid"; done
    attempts=0
    while [ -n "$(app_pids)" ]; do
        attempts=$((attempts + 1))
        [ "$attempts" -le 10 ] || die "YouTube did not stop; no force kill was used"
        sleep 1
    done
}

backup_payload() {
    set -- cobalt
    [ ! -e "$APP/content" ] || set -- "$@" content
    [ ! -e "$APP/lib" ] || set -- "$@" lib
    (cd "$APP" && tar -cpf "$BACKUP/stock-payload.tar" "$@")
    chmod 600 "$BACKUP/stock-payload.tar"
    sha "$BACKUP/stock-payload.tar" > "$BACKUP/stock-payload.sha256"
    printf '%s\n' "$APP" > "$BACKUP/app-dir"
    sha "$APP/appinfo.json" > "$BACKUP/appinfo.sha256"
    chmod 600 "$BACKUP"/*
}

restore_payload() {
    expected=$(cat "$BACKUP/stock-payload.sha256")
    [ "$(sha "$BACKUP/stock-payload.tar")" = "$expected" ] || die "Backup hash mismatch; refusing restore"
    rm -rf "$APP/cobalt" "$APP/cobalt.real" "$APP/content" "$APP/lib"
    tar -xpf "$BACKUP/stock-payload.tar" -C "$APP"
    # Profiles outside these payload folders were not changed. A vendor profile
    # inside content is restored from the private, on-TV-only preinstall backup.
    # Leave the separate RF profile in place; do not delete account data implicitly.
}

validate_mount_layout() {
    mount_ro=$(awk -v target="$APP" '
      {m=$5; if (m=="/" || target==m || index(target,m"/")==1) {
        if(length(m)>longest){longest=length(m);opts=$6;line=$0}
      }} END {if(!longest){print "unknown";exit} split(","opts",",a,",");ro="no";
        for(i in a)if(a[i]=="ro")ro="yes"; print ro}' "$MOUNTINFO")
    [ "$mount_ro" = no ] || die "Read-only/unknown app mount: no remount is supported"
    exact_count=$(awk -v p="$APP" '$5==p{n++}END{print n+0}' "$MOUNTINFO")
    [ "$exact_count" -le 1 ] || die "Ambiguous stacked app mounts; remove temporary bind mounts first"
    MOUNT_KIND=directory
    if [ "$exact_count" = 1 ]; then
        overlay_options=$(awk -v p="$APP" '$5==p{split($0,a," - ");split(a[2],b," ");if(b[1]!="overlay")exit 1;print b[3]}' "$MOUNTINFO") || die "App mount is not a supported persistent overlay"
        upper=$(printf '%s\n' "$overlay_options" | tr ',' '\n' | sed -n 's/^upperdir=//p')
        lower=$(printf '%s\n' "$overlay_options" | tr ',' '\n' | sed -n 's/^lowerdir=//p')
        work=$(printf '%s\n' "$overlay_options" | tr ',' '\n' | sed -n 's/^workdir=//p')
        [ "$upper" = "$APP" ] || die "Overlay upperdir must be the persistent application path"
        [ "$lower" = "/media/squashfs/apps/$APP_ID/usr/palm/applications/$APP_ID" ] || die "Unknown overlay lowerdir"
        [ "$work" = "/media/squashfs/work/$APP_ID" ] || die "Unknown overlay workdir"
        MOUNT_KIND=overlay
    fi
    mount_fs=$(awk -v target="$APP" '{m=$5;if(m=="/"||target==m||index(target,m"/")==1)if(length(m)>n){n=length(m);split($0,a," - ");split(a[2],b," ");f=b[1]}}END{print f}' "$MOUNTINFO")
    case "$mount_fs" in tmpfs|ramfs|squashfs|'') die "Volatile/read-only/unknown app filesystem is not supported" ;; esac
    # Child mounts would make payload backup/restore ambiguous.
    awk -v p="$APP/" 'index($5,p)==1{found=1}END{exit !found}' "$MOUNTINFO" && die "Application contains child mounts" || :
}

persistent_backing() {
    # Ignore the app overlay itself when examining the underlying upper directory.
    backing=$(awk -v target="$1" -v app="$APP" '$5!=app{m=$5;if(m=="/"||target==m||index(target,m"/")==1)if(length(m)>n){n=length(m);split($0,a," - ");split(a[2],b," ");f=b[1];o=$6}}END{print f":"o}' "$MOUNTINFO")
    case "$backing" in
        ext2:*|ext3:*|ext4:*|f2fs:*|btrfs:*|xfs:*|ubifs:*|cryptofs:*|ecryptfs:*|fuse:*|fuse.*:*) ;;
        *) die "Overlay backing storage is not a verified persistent filesystem" ;;
    esac
    case ",${backing#*:}," in *,ro,*) die "Overlay backing storage is read-only" ;; esac
}

mount_check() {
    validate_mount_layout
    [ -w "$APP" ] || die "Application directory is not already writable"
    if [ "$MOUNT_KIND" = overlay ]; then
        [ -d "$work" ] && [ ! -L "$work" ] && [ -w "$work" ] || die "Overlay work directory is not writable/canonical"
        [ -d "$lower" ] && [ ! -L "$lower" ] || die "Overlay lower directory is not canonical"
        persistent_backing "${APP%/*}"
        persistent_backing "$work"
    else
        persistent_backing "$APP"
    fi
}

abi_info() {
    abi_file=$APP/cobalt
    [ ! -f "$APP/cobalt.real" ] || abi_file=$APP/cobalt.real
    set -- $(od -An -tu1 -N20 "$abi_file")
    STOCK_ABI=unsupported
    if [ "$#" -eq 20 ] && [ "$1:$2:$3:$4:$5:$6:${19}:${20}" = "127:69:76:70:1:1:40:0" ]; then
        STOCK_ABI=elf32-little-arm
    fi
    LOADER_GLOBAL=no; LOADER_JAIL=unknown
    [ ! -e /lib/ld-linux.so.3 ] || LOADER_GLOBAL=yes
    if [ -n "${selected:-}" ]; then
        LOADER_JAIL=no
        [ ! -e "/proc/$selected/root/lib/ld-linux.so.3" ] || LOADER_JAIL=yes
    fi
}

doctor() {
    choose_app "$1"
    printf 'app_dir\t%s\n' "$APP"
    printf 'manifest\t'; tr -d '\r\n' < "$APP/appinfo.json"; printf '\n'
    printf 'manifest_sha256\t%s\n' "$(sha "$APP/appinfo.json")"
    printf 'cobalt_sha256\t%s\n' "$(sha "$APP/cobalt")"
    if [ -e "$APP/cobalt.real" ]; then printf 'cobalt_real_exists\tyes\n'; else printf 'cobalt_real_exists\tno\n'; fi
    if [ -w "$APP" ]; then printf 'writable\tyes\n'; else printf 'writable\tno\n'; fi
    ro=$(awk -v target="$APP" '{m=$5;if(m=="/"||target==m||index(target,m"/")==1)if(length(m)>n){n=length(m);o=$6}}END{if(!n){print "unknown";exit}if((","o",")~/,ro,/)print "yes";else print "no"}' /proc/self/mountinfo)
    printf 'mount_ro\t%s\n' "$ro"
    count=0; selected=
    for pid in $(app_pids); do count=$((count + 1)); selected=$pid; done
    printf 'runtime_count\t%s\n' "$count"
    if [ "$count" = 1 ]; then
        printf 'runtime_pid\t%s\n' "$selected"
        awk '$1=="Uid:"{printf "runtime_uid\t%s\n",$3}$1=="Gid:"{printf "runtime_gid\t%s\n",$3}' "/proc/$selected/status"
    fi
    abi_info
    printf 'uname_machine\t%s\n' "$(uname -m)"
    printf 'entrypoint_abi\t%s\nloader_global\t%s\nloader_jail\t%s\n' "$STOCK_ABI" "$LOADER_GLOBAL" "$LOADER_JAIL"
    if [ -f "$STATE/ACTIVE" ]; then printf 'kit_active\tyes\n'; else printf 'kit_active\tno\n'; fi
    if [ -f "$STATE/PENDING" ]; then printf 'kit_pending\tyes\n'; else printf 'kit_pending\tno\n'; fi
}

install() {
    APP=$1; INSTALL_ID=$2; UPLOAD_SHA=$3; MANIFEST_SHA=$4; OLD_SHA=$5; PID=$6; RUN_UID=$7; RUN_GID=$8; DISABLE_AV1=$9
    validate_app
    case "$INSTALL_ID" in *[!0-9TZabcdef-]*|'') die "Invalid installation id" ;; esac
    case "$PID:$RUN_UID:$RUN_GID" in *[!0-9:]*|'') die "Invalid runtime identity" ;; esac
    [ "$RUN_UID" -gt 0 ] || die "Refusing a root app profile"
    mkdir -p "$STATE"; chmod 700 "$STATE"
    acquire_lock
    trap 'release_lock' EXIT
    [ ! -e "$STATE/ACTIVE" ] || die "An installation is already active; rollback first"
    [ ! -e "$STATE/PENDING" ] || die "An interrupted transaction needs rollback first"
    mount_check
    [ "$(sha "$APP/appinfo.json")" = "$MANIFEST_SHA" ] || die "App metadata changed since doctor"
    [ "$(sha "$APP/cobalt")" = "$OLD_SHA" ] || die "App executable changed since doctor"
    [ "$(app_pids)" = "$PID" ] || die "App process changed since doctor; retry"
    [ "$(awk '$1=="Uid:"{print $3}' "/proc/$PID/status")" = "$RUN_UID" ] || die "Runtime identity changed"
    [ "$(awk '$1=="Gid:"{print $3}' "/proc/$PID/status")" = "$RUN_GID" ] || die "Runtime group changed"
    selected=$PID
    abi_info
    [ "$STOCK_ABI" = elf32-little-arm ] && [ "$LOADER_GLOBAL" = yes ] && [ "$LOADER_JAIL" = yes ] || die "Unsupported/unknown ARM32 runtime ABI or loader"
    incoming="$STATE/incoming-$INSTALL_ID.tar"
    [ -f "$incoming" ] && [ "$(sha "$incoming")" = "$UPLOAD_SHA" ] || die "Staged payload hash mismatch"
    BACKUP="$STATE/backups/$INSTALL_ID"
    mkdir -p "$BACKUP"; chmod 700 "$STATE/backups" "$BACKUP"
    unpacked="$BACKUP/new-payload"
    mkdir "$unpacked"
    tar -xpf "$incoming" -C "$unpacked"
    [ "$(sha "$unpacked/cobalt")" = "$ELF_SHA" ] || die "Staged RF ELF mismatch"
    stop_app
    backup_payload
    phase=prepared
    trap 'status=$?; if [ "$status" -ne 0 ] && [ "$phase" = replacing ]; then if [ "$(sha "$APP/appinfo.json")" = "$MANIFEST_SHA" ]; then restore_payload; rm -f "$STATE/PENDING" "$STATE/ACTIVE" "$STATE/ACTIVE.tmp"; sync; else echo "youtube-kit: metadata changed; pending backup retained for manual review" >&2; fi; fi; release_lock; exit "$status"' EXIT
    [ -z "$(app_pids)" ] || die "YouTube restarted during staging; retry when idle"
    journal_pending
    phase=replacing
    rm -rf "$APP/cobalt" "$APP/cobalt.real" "$APP/content" "$APP/lib"
    cp -a "$unpacked/content" "$APP/content"
    [ ! -d "$unpacked/lib" ] || cp -a "$unpacked/lib" "$APP/lib"
    cp -p "$unpacked/cobalt" "$APP/cobalt.real"; chmod 755 "$APP/cobalt.real"
    profile=".youtube-kit-profile-$INSTALL_ID"
    mkdir "$APP/$profile"; chown "$RUN_UID:$RUN_GID" "$APP/$profile"; chmod 700 "$APP/$profile"
    {
        printf '%s\n' '#!/bin/sh' '# youtube-kit-entrypoint-v1' 'set -eu'
        printf '%s\n' 'case "$0" in */*) app_dir=${0%/*} ;; *) echo "youtube-kit: absolute app entrypoint required" >&2; exit 1 ;; esac'
        printf 'export HOME="$app_dir/%s"\n' "$profile"
        if [ "$DISABLE_AV1" = yes ]; then
            printf '%s\n' 'exec "$app_dir/cobalt.real" --disable_media_codecs=av01 "$@"'
        else
            printf '%s\n' 'exec "$app_dir/cobalt.real" "$@"'
        fi
    } > "$APP/cobalt"
    chmod 755 "$APP/cobalt"
    [ "$(sha "$APP/appinfo.json")" = "$MANIFEST_SHA" ] || die "App metadata changed unexpectedly"
    [ "$(sha "$APP/cobalt.real")" = "$ELF_SHA" ] || die "Installed ELF mismatch"
    sha "$APP/cobalt" > "$BACKUP/wrapper.sha256"
    printf '%s\n' "$profile" > "$BACKUP/profile-name"
    printf '%s\n' "$INSTALL_ID" > "$STATE/ACTIVE.tmp"
    mv "$STATE/ACTIVE.tmp" "$STATE/ACTIVE"
    sync
    rm -f "$STATE/PENDING"
    sync
    phase=committed
    rm -f "$incoming"
    echo "installed; stock metadata preserved; open YouTube manually and validate playback/relaunch"
}

rollback() {
    recovery=no
    if [ -f "$STATE/PENDING" ]; then
        recovery=yes; INSTALL_ID=$(cat "$STATE/PENDING")
        [ ! -f "$STATE/ACTIVE" ] || [ "$(cat "$STATE/ACTIVE")" = "$INSTALL_ID" ] || die "Conflicting transaction journals"
    elif [ -f "$STATE/ACTIVE" ]; then
        INSTALL_ID=$(cat "$STATE/ACTIVE")
    else
        echo "no active installation"; return
    fi
    case "$INSTALL_ID" in *[!0-9TZabcdef-]*|'') die "Invalid active installation id" ;; esac
    BACKUP="$STATE/backups/$INSTALL_ID"
    APP=$(cat "$BACKUP/app-dir")
    [ -z "$1" ] || [ "$1" = "$APP" ] || die "Requested app directory differs from backup"
    validate_metadata
    mount_check
    [ "$(sha "$APP/appinfo.json")" = "$(cat "$BACKUP/appinfo.sha256")" ] || die "App metadata changed; refusing to overwrite a later app update"
    [ "$(sha "$BACKUP/stock-payload.tar")" = "$(cat "$BACKUP/stock-payload.sha256")" ] || die "Backup hash mismatch; refusing restore"
    if [ "$recovery" = no ]; then
        [ -f "$APP/cobalt" ] && [ "$(sha "$APP/cobalt")" = "$(cat "$BACKUP/wrapper.sha256")" ] || die "Entrypoint changed; manual review required"
    fi
    acquire_lock
    trap 'release_lock' EXIT
    stop_app
    journal_pending
    restore_payload
    sync
    rm -f "$STATE/ACTIVE" "$STATE/PENDING"
    sync
    echo "rolled back; original profile untouched; separate RF profile retained privately on TV"
}

_main() {
    [ "$(id -u)" = 0 ] || die "Existing root SSH access is required"
    command -v sha256sum >/dev/null || die "sha256sum is required"
    command -v tar >/dev/null || die "tar is required"
    command -v od >/dev/null || die "od is required for the ARM32 preflight"
    mode=$1; shift
    case "$mode" in
        doctor) doctor "$@" ;;
        install) install "$@" ;;
        rollback) rollback "$@" ;;
        *) die "Unknown operation" ;;
    esac
}

_main "$@"

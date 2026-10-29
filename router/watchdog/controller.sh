# SPDX-License-Identifier: MIT
# POSIX ash controller. Source after backend.sh; call tick every 120 seconds.
# Backend operations must be bounded. Rollback must not restart disabled service.
: "${FAILURES:=0}" "${LAST_ATTEMPT:=0}" "${LAST_RUNTIME_ATTEMPT:=0}"
: "${HEALTH_FAIL_LIMIT:=3}" "${COOLDOWN:=1800}" "${BOOT_GRACE:=180}"
# Backend supplies only live-validated candidates; empty means no adoption.
: "${CANDIDATES:=}" "${ROLLBACK_BLOCKED:=0}"
: "${STATUS:=}" "${STATUS_DETAILS:=}"

_wd_status() {
    if [ "$STATUS" != "$1" ] || [ "$STATUS_DETAILS" != "$2" ]; then
        STATUS=$1 STATUS_DETAILS=$2
        emit_status "$STATUS" "$STATUS_DETAILS" || :
    fi
}

_wd_call() {
    if "$@"; then WD_RC=0; else WD_RC=$?; fi
}

_wd_enabled() {
    if is_enabled; then return 0; fi
    FAILURES=0
    _wd_status paused disabled
    return 1
}

_wd_controls() {
    _wd_call controls_ok
    case "$WD_RC" in
        0) return 0 ;;
        1) WD_CONTROL_STATUS=internet_outage ;;
        *) WD_CONTROL_STATUS=internet_unknown ;;
    esac
    FAILURES=0
    _wd_status paused "$WD_CONTROL_STATUS"
    return 1
}

_wd_cooling() {
    [ "$1" -gt 0 ] && [ "$WD_NOW" -ge "$1" ] &&
        [ "$((WD_NOW - $1))" -lt "$COOLDOWN" ]
}

_wd_rollback() {
    if trial_rollback; then return 0; fi
    ROLLBACK_BLOCKED=1 FAILURES=0
    _wd_status rollback_failed manual_recovery_required
    return 1
}

_wd_repair_runtime() {
    FAILURES=0
    if _wd_cooling "$LAST_RUNTIME_ATTEMPT"; then
        _wd_status runtime_cooldown repair_throttled
        return 0
    fi
    _wd_enabled || return 0
    LAST_RUNTIME_ATTEMPT=$WD_NOW
    _wd_call recover_runtime
    WD_REPAIR_RC=$WD_RC
    _wd_call runtime_ok
    if [ "$WD_RC" -ne 0 ]; then
        _wd_status runtime_failed "repair=$WD_REPAIR_RC"
        return 0
    fi
    # A repaired daemon is checked, but this tick never changes profiles.
    _wd_call probe_current
    case "$WD_RC" in
        0) _wd_status runtime_recovered youtube_healthy ;;
        1) _wd_status runtime_recovered youtube_failed ;;
        *) _wd_status runtime_recovered youtube_unknown ;;
    esac
}

tick() {
    _wd_enabled || return 0
    if ! WD_NOW=$(uptime_seconds); then WD_NOW=; fi
    case "$WD_NOW" in
        ''|*[!0-9]*) FAILURES=0; _wd_status paused uptime_unknown; return 0 ;;
    esac
    if [ "$WD_NOW" -lt "$BOOT_GRACE" ]; then
        FAILURES=0
        _wd_status paused boot_grace
        return 0
    fi
    if [ "$ROLLBACK_BLOCKED" -ne 0 ]; then
        _wd_status rollback_failed manual_recovery_required
        return 0
    fi
    _wd_controls || return 0
    _wd_call runtime_ok
    if [ "$WD_RC" -ne 0 ]; then
        _wd_repair_runtime
        return 0
    fi
    _wd_call probe_current
    case "$WD_RC" in
        0) FAILURES=0; _wd_status healthy "profile=$CURRENT_PROFILE"; return 0 ;;
        1) : ;;
        *) FAILURES=0; _wd_status indeterminate current_probe; return 0 ;;
    esac
    if [ "$FAILURES" -lt "$HEALTH_FAIL_LIMIT" ]; then
        FAILURES=$((FAILURES + 1))
    fi
    if [ "$FAILURES" -lt "$HEALTH_FAIL_LIMIT" ]; then
        _wd_status suspect "failures=$FAILURES"
        return 0
    fi
    if _wd_cooling "$LAST_ATTEMPT"; then
        _wd_status cooldown profile_attempt_throttled
        return 0
    fi
    # Recheck the current profile before any isolated candidate testing.
    _wd_call probe_current
    case "$WD_RC" in
        0) FAILURES=0; _wd_status healthy "profile=$CURRENT_PROFILE"; return 0 ;;
        1) : ;;
        *) FAILURES=0; _wd_status indeterminate current_recheck; return 0 ;;
    esac
    _wd_controls || return 0
    _wd_enabled || return 0
    LAST_ATTEMPT=$WD_NOW
    for WD_CANDIDATE in $CANDIDATES; do
        [ "$WD_CANDIDATE" != "$CURRENT_PROFILE" ] || continue
        _wd_enabled || return 0
        _wd_call probe_candidate "$WD_CANDIDATE"
        [ "$WD_RC" -eq 0 ] || continue
        pause_between_probes 3
        _wd_call probe_candidate "$WD_CANDIDATE"
        [ "$WD_RC" -eq 0 ] || continue
        # Candidate checks take time: the current profile may have recovered.
        _wd_call probe_current
        case "$WD_RC" in
            0) FAILURES=0; _wd_status healthy "profile=$CURRENT_PROFILE"; return 0 ;;
            1) : ;;
            *) FAILURES=0; _wd_status indeterminate pretrial_recheck; return 0 ;;
        esac
        _wd_controls || return 0
        _wd_enabled || return 0
        _wd_status trial "profile=$WD_CANDIDATE"
        _wd_call trial_start "$WD_CANDIDATE"
        WD_TRIAL_OK=0
        if [ "$WD_RC" -eq 0 ]; then
            _wd_call trial_verify
            if [ "$WD_RC" -eq 0 ]; then
                pause_between_probes 3
                if _wd_enabled; then
                    _wd_call trial_verify
                    [ "$WD_RC" -ne 0 ] || WD_TRIAL_OK=1
                fi
            fi
        fi
        if [ "$WD_TRIAL_OK" -eq 1 ] && _wd_enabled && _wd_controls; then
            if trial_commit "$WD_CANDIDATE"; then
                CURRENT_PROFILE=$WD_CANDIDATE FAILURES=0
                _wd_status switched "profile=$CURRENT_PROFILE"
                return 0
            fi
        fi
        # Failed starts/commits may also have partially applied a RAM override.
        _wd_rollback || return 0
        _wd_enabled || return 0
        _wd_controls || return 0
        _wd_status rolled_back "profile=$WD_CANDIDATE"
    done
    FAILURES=0
    _wd_status no_candidate isolated_or_production_checks_failed
    return 0
}

#!/usr/bin/env python3
"""Run the actual sourced POSIX controller against deterministic local backends."""
import pathlib
import shlex
import subprocess
import tempfile
import unittest

CONTROLLER = pathlib.Path(__file__).resolve().parents[1] / "watchdog" / "controller.sh"
BACKEND = r'''
mock_call() {
    op=$1; shift
    printf '%s' "$op" >>"$TEST_ROOT/trace"
    for arg in "$@"; do printf ' %s' "$arg" >>"$TEST_ROOT/trace"; done
    printf '\n' >>"$TEST_ROOT/trace"
    rc=0
    if [ -s "$TEST_ROOT/$op" ]; then
        IFS= read -r rc <"$TEST_ROOT/$op"
        sed '1d' "$TEST_ROOT/$op" >"$TEST_ROOT/$op.next"
        mv "$TEST_ROOT/$op.next" "$TEST_ROOT/$op"
    fi
    return "$rc"
}
is_enabled() { mock_call enabled; }
uptime_seconds() { printf '%s\n' "$NOW"; }
controls_ok() { mock_call controls; }
runtime_ok() { mock_call runtime; }
recover_runtime() { mock_call recover; }
probe_current() { mock_call current; }
probe_candidate() { mock_call "candidate_$1"; }
trial_start() { mock_call "start_$1"; }
trial_verify() { mock_call verify; }
trial_commit() { mock_call "commit_$1"; }
trial_rollback() { mock_call rollback; }
pause_between_probes() { mock_call pause "$@"; }
emit_status() { printf 'status %s %s\n' "$1" "$2" >>"$TEST_ROOT/trace"; }
'''


class ControllerTests(unittest.TestCase):
    def run_ticks(self, plan=None, ticks=3, setup="", actions=None):
        with tempfile.TemporaryDirectory(prefix="youtube-controller-") as directory:
            root = pathlib.Path(directory)
            for name, codes in (plan or {}).items():
                (root / name).write_text("".join(str(code) + "\n" for code in codes))
            (root / "trace").touch()
            tick_code = actions or "\n".join("tick" for _ in range(ticks))
            script = (
                "set -eu\nTEST_ROOT=" + shlex.quote(directory) + "\n"
                + BACKEND + "\nCURRENT_PROFILE=multisplit\nCANDIDATES='split hostsplit'\nNOW=1000\n"
                + ". " + shlex.quote(str(CONTROLLER)) + "\n" + setup + "\n"
                + tick_code + "\n"
                + 'printf "FINAL|%s|%s|%s|%s|%s\\n" "$CURRENT_PROFILE" '
                  '"$FAILURES" "$LAST_ATTEMPT" "$LAST_RUNTIME_ATTEMPT" "$STATUS"\n'
            )
            result = subprocess.run(["/bin/sh", "-c", script], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            trace = (root / "trace").read_text().splitlines()
            final = result.stdout.strip().split("|")
            return trace, final

    def assert_no_mutation(self, trace):
        self.assertFalse(any(line.startswith(("start_", "commit_", "recover", "rollback"))
                             for line in trace), trace)

    def test_healthy_and_status_deduplication(self):
        trace, final = self.run_ticks()
        self.assert_no_mutation(trace)
        self.assertEqual(sum(x.startswith("status healthy") for x in trace), 1)
        self.assertEqual(final[1:3], ["multisplit", "0"])

    def test_three_failures_and_two_isolated_and_production_passes(self):
        trace, final = self.run_ticks({"current": [1, 1, 1, 1, 1]})
        self.assertEqual(trace.count("candidate_split"), 2)
        self.assertEqual(trace.count("verify"), 2)
        self.assertEqual(trace.count("pause 3"), 2)
        self.assertEqual(trace.count("start_split"), 1)
        self.assertEqual(trace.count("commit_split"), 1)
        self.assertEqual(final[1:3], ["split", "0"])

    def test_outage_never_changes_or_repairs(self):
        trace, final = self.run_ticks({"controls": [1, 1, 1]}, setup="FAILURES=2")
        self.assert_no_mutation(trace)
        self.assertNotIn("current", trace)
        self.assertEqual(final[2], "0")

    def test_profile_cooldown(self):
        trace, _ = self.run_ticks({"current": [1, 1, 1]}, setup="LAST_ATTEMPT=900")
        self.assert_no_mutation(trace)
        self.assertNotIn("candidate_split", trace)

    def test_indeterminate_current_resets_failure_streak(self):
        trace, final = self.run_ticks({"current": [1, 2, 1]})
        self.assert_no_mutation(trace)
        self.assertEqual(final[2], "1")

    def test_indeterminate_recheck_prevents_candidate_scan(self):
        trace, final = self.run_ticks({"current": [1, 1, 1, 2]})
        self.assert_no_mutation(trace)
        self.assertNotIn("candidate_split", trace)
        self.assertEqual(final[2], "0")

    def test_trial_rollback_then_try_next_candidate(self):
        trace, final = self.run_ticks({"current": [1, 1, 1, 1, 1, 1], "verify": [1, 0, 0]})
        self.assertEqual(trace.count("rollback"), 1)
        self.assertNotIn("commit_split", trace)
        self.assertEqual(trace.count("commit_hostsplit"), 1)
        self.assertLess(trace.index("rollback"), trace.index("start_hostsplit"))
        self.assertEqual(final[1], "hostsplit")

    def test_all_candidate_failures_or_unknown_leave_production_untouched(self):
        trace, final = self.run_ticks({"current": [1, 1, 1, 1],
                                      "candidate_split": [1], "candidate_hostsplit": [2]})
        self.assert_no_mutation(trace)
        self.assertEqual(final[1], "multisplit")
        self.assertEqual(final[-1], "no_candidate")

    def test_failed_second_isolated_pass_is_not_adopted(self):
        trace, _ = self.run_ticks({"current": [1, 1, 1, 1],
                                  "candidate_split": [0, 2], "candidate_hostsplit": [1]})
        self.assert_no_mutation(trace)

    def test_daemon_repair_has_own_cooldown_and_does_not_flip_profiles(self):
        trace, final = self.run_ticks({"runtime": [1, 0, 1, 1], "current": [1]},
                                      setup="LAST_ATTEMPT=900")
        self.assertEqual(trace.count("recover"), 1)
        self.assertFalse(any(x.startswith(("start_", "commit_")) for x in trace))
        self.assertEqual(final[1], "multisplit")
        self.assertEqual(final[4], "1000")

    def test_disabled_never_probes_or_restarts(self):
        trace, final = self.run_ticks({"enabled": [1, 1, 1]}, setup="FAILURES=2")
        self.assert_no_mutation(trace)
        self.assertNotIn("controls", trace)
        self.assertEqual(final[2], "0")

    def test_boot_grace(self):
        trace, _ = self.run_ticks(setup="NOW=179")
        self.assert_no_mutation(trace)
        self.assertNotIn("controls", trace)

    def test_current_recheck_recovery_prevents_trial(self):
        trace, final = self.run_ticks({"current": [1, 1, 1, 0]})
        self.assert_no_mutation(trace)
        self.assertEqual(final[-1], "healthy")

    def test_failed_trial_start_is_rolled_back_before_next_candidate(self):
        trace, final = self.run_ticks({"current": [1, 1, 1, 1, 1, 1], "start_split": [1]})
        self.assertLess(trace.index("rollback"), trace.index("start_hostsplit"))
        self.assertEqual(final[1], "hostsplit")

    def test_failed_commit_is_rolled_back(self):
        trace, final = self.run_ticks({"current": [1, 1, 1, 1, 1], "commit_split": [1],
                                      "candidate_hostsplit": [1]})
        self.assertEqual(trace.count("rollback"), 1)
        self.assertEqual(final[1], "multisplit")

    def test_failed_rollback_blocks_subsequent_mutation(self):
        trace, final = self.run_ticks({"current": [1, 1, 1, 1, 1], "verify": [1],
                                      "rollback": [1]}, ticks=4)
        self.assertEqual(trace.count("start_split"), 1)
        self.assertNotIn("start_hostsplit", trace)
        self.assertEqual(final[-1], "rollback_failed")

    def test_disabled_during_isolated_probe_never_starts_trial(self):
        trace, final = self.run_ticks({"current": [1, 1, 1, 1, 1],
                                      "enabled": [0, 0, 0, 0, 0, 1]})
        self.assert_no_mutation(trace)
        self.assertEqual(final[-1], "paused")

    def test_disabled_during_trial_rolls_back_without_committing(self):
        trace, final = self.run_ticks({"current": [1, 1, 1, 1, 1],
                                      "enabled": [0, 0, 0, 0, 0, 0, 1, 1]})
        self.assertEqual(trace.count("rollback"), 1)
        self.assertFalse(any(x.startswith("commit_") for x in trace))
        self.assertNotIn("start_hostsplit", trace)
        self.assertEqual(final[-1], "paused")

    def test_unknown_production_probe_rolls_back(self):
        trace, final = self.run_ticks({"current": [1, 1, 1, 1, 1], "verify": [2],
                                      "candidate_hostsplit": [1]})
        self.assertEqual(trace.count("rollback"), 1)
        self.assertFalse(any(x.startswith("commit_") for x in trace))
        self.assertEqual(final[1:3], ["multisplit", "0"])

    def test_cooldown_expires_at_exact_boundary(self):
        trace, final = self.run_ticks({"current": [1, 1, 1, 1]},
                                      setup="FAILURES=2\nLAST_ATTEMPT=900",
                                      actions="NOW=2699\ntick\nNOW=2700\ntick")
        self.assertEqual(trace.count("commit_split"), 1)
        self.assertEqual(final[3], "2700")

    def test_unvalidated_empty_candidates_never_mutates_production(self):
        trace, final = self.run_ticks({"current": [1, 1, 1, 1]}, setup="CANDIDATES=''")
        self.assert_no_mutation(trace)
        self.assertEqual(final[1], "multisplit")

    def test_control_unknown_resets_failure_streak(self):
        trace, final = self.run_ticks({"controls": [2, 2, 2]}, setup="FAILURES=2")
        self.assert_no_mutation(trace)
        self.assertEqual(final[2], "0")

    def test_current_recovers_during_candidate_probes_no_trial(self):
        trace, final = self.run_ticks({"current": [1, 1, 1, 1, 0]})
        self.assertEqual(trace.count("candidate_split"), 2)
        self.assertEqual(trace.count("current"), 5)
        self.assert_no_mutation(trace)
        self.assertEqual(final[1:3], ["multisplit", "0"])
        self.assertEqual(final[-1], "healthy")

    def test_current_becomes_unknown_during_candidate_probes_no_trial(self):
        trace, final = self.run_ticks({"current": [1, 1, 1, 1, 2]})
        self.assertEqual(trace.count("candidate_split"), 2)
        self.assert_no_mutation(trace)
        self.assertEqual(final[1:3], ["multisplit", "0"])
        self.assertEqual(final[-1], "indeterminate")


if __name__ == "__main__":
    unittest.main(verbosity=2)

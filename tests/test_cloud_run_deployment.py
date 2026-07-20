from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


class CloudRunContainerTests(unittest.TestCase):
    def test_container_uses_locked_runtime_and_cloud_run_port(self) -> None:
        dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text()
        self.assertIn("--require-hashes -r requirements.lock", dockerfile)
        self.assertIn("--host 0.0.0.0", dockerfile)
        self.assertIn('--port "${PORT:-8080}"', dockerfile)
        self.assertIn("USER spooky", dockerfile)

    def test_container_copies_only_runtime_packages(self) -> None:
        dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text()
        self.assertIn("COPY search_agent_lab ./search_agent_lab", dockerfile)
        self.assertIn("COPY spooky ./spooky", dockerfile)
        self.assertNotIn("COPY . ", dockerfile)
        self.assertNotIn("GOOGLE_API_KEY", dockerfile)

    def test_cloud_build_and_image_contexts_exclude_credentials(self) -> None:
        for ignore_file in (".gcloudignore", ".dockerignore"):
            with self.subTest(ignore_file=ignore_file):
                patterns = (REPOSITORY_ROOT / ignore_file).read_text().splitlines()
                self.assertIn(".env", patterns)
                self.assertIn(".env.*", patterns)
                self.assertIn("service-account-key.json", patterns)
                self.assertIn("service-account-*.json", patterns)
                self.assertIn("google-service-account-*.json", patterns)


class CloudRunRunbookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runbook = (REPOSITORY_ROOT / "docs/spooky-cloud-run.md").read_text()

    def test_runbook_uses_vertex_service_identity_without_static_secrets(
        self,
    ) -> None:
        self.assertIn("GOOGLE_GENAI_USE_ENTERPRISE=True", self.runbook)
        self.assertIn("GOOGLE_CLOUD_PROJECT=${TASK_PROJECT}", self.runbook)
        self.assertIn(
            "GOOGLE_CLOUD_LOCATION=${TASK_MODEL_LOCATION}", self.runbook
        )
        self.assertIn("roles/aiplatform.user", self.runbook)
        self.assertNotIn("--set-secrets", self.runbook)
        self.assertNotIn("spooky-gemini-api-key", self.runbook)

    def test_runbook_keeps_deploy_build_and_runtime_roles_separate(self) -> None:
        self.assertIn("roles/run.sourceDeveloper", self.runbook)
        self.assertIn("roles/serviceusage.serviceUsageConsumer", self.runbook)
        self.assertIn("roles/run.builder", self.runbook)
        self.assertIn("roles/iam.serviceAccountUser", self.runbook)
        self.assertIn(
            "759544311265-compute@developer.gserviceaccount.com",
            self.runbook,
        )
        self.assertIn(
            "spooky-api-runtime@search-agent-lab.iam.gserviceaccount.com",
            self.runbook,
        )

    def test_runbook_pins_source_and_verifies_privately_before_public(self) -> None:
        detached_checkout = self.runbook.index(
            'git checkout --detach "$TASK_COMMIT"'
        )
        private_deploy = self.runbook.index("--invoker-iam-check")
        public_open = self.runbook.index("--no-invoker-iam-check")
        self.assertLess(detached_checkout, private_deploy)
        self.assertLess(private_deploy, public_open)
        self.assertIn("test -z \"$(git status --porcelain)\"", self.runbook)
        self.assertIn('TASK_MODEL="gemini-3.5-flash"', self.runbook)

    def test_runbook_projects_only_safe_log_metadata(self) -> None:
        self.assertIn("gcloud logging read", self.runbook)
        self.assertNotIn("gcloud run services logs read", self.runbook)
        self.assertIn("httpRequest.requestMethod", self.runbook)
        self.assertIn("httpRequest.status", self.runbook)
        self.assertIn("resource.labels.revision_name", self.runbook)

    def test_diagnostic_revision_keeps_zero_traffic_and_allowlisted_logs(
        self,
    ) -> None:
        diagnostic = self.runbook.split(
            "## Diagnose a provider failure without moving traffic", 1
        )[1].split("## Open publicly", 1)[0]
        self.assertIn("--no-traffic", diagnostic)
        self.assertIn("--tag provider-diag", diagnostic)
        self.assertIn("--invoker-iam-check", diagnostic)
        self.assertIn('test "$(git rev-parse HEAD)" = "$TASK_COMMIT"', diagnostic)
        self.assertIn('test -z "$(git status --porcelain)"', diagnostic)

        baseline = diagnostic.index('TASK_PRIOR_REVISION="$(jq')
        exact_sha = diagnostic.index('test "$(git rev-parse HEAD)"')
        clean_tree = diagnostic.index('test -z "$(git status --porcelain)"')
        exit_trap = diagnostic.index("trap spooky_diag_exit EXIT")
        deploy = diagnostic.index('gcloud run deploy "$TASK_SERVICE"')
        traffic_assertion = diagnostic.index(
            '--arg diagnostic "$TASK_DIAG_REVISION"'
        )
        private_assertion = diagnostic.index(
            'index("allUsers") == null', traffic_assertion
        )
        unauthenticated_403 = diagnostic.index(
            'test "$TASK_TAGGED_UNAUTH_STATUS" = "403"'
        )
        success = diagnostic.index("diagnostic-deployment-gate=passed")
        diagnostic_request = diagnostic.index("The first-stage experiment")
        self.assertLess(exact_sha, deploy)
        self.assertLess(clean_tree, deploy)
        self.assertLess(baseline, deploy)
        self.assertLess(exit_trap, deploy)
        self.assertLess(deploy, traffic_assertion)
        self.assertLess(traffic_assertion, private_assertion)
        self.assertLess(private_assertion, unauthenticated_403)
        self.assertLess(unauthenticated_403, success)
        self.assertLess(success, diagnostic_request)

        recovery = diagnostic.split("spooky_diag_recover()", 1)[1].split(
            "spooky_diag_exit()", 1
        )[0]
        private_restore = recovery.index("--invoker-iam-check")
        traffic_restore = recovery.index("--to-revisions")
        tag_removal = recovery.index("--remove-tags provider-diag")
        self.assertLess(private_restore, traffic_restore)
        self.assertLess(traffic_restore, tag_removal)
        self.assertIn('.tag == "provider-diag"', recovery)
        self.assertIn('index("allUsers") == null', recovery)
        self.assertIn("diagnostic-drift-recovery=passed", recovery)

        exit_handler = diagnostic.split("spooky_diag_exit()", 1)[1].split(
            'test "$(git rev-parse HEAD)"', 1
        )[0]
        self.assertIn('local exit_status="$?"', exit_handler)
        self.assertIn("spooky_diag_recover || true", exit_handler)
        self.assertIn('exit "$exit_status"', exit_handler)
        self.assertNotIn("local status=", diagnostic)

        invoker_annotation = diagnostic.index(
            'run.googleapis.com/invoker-iam-disabled', traffic_assertion
        )
        self.assertLess(invoker_annotation, unauthenticated_403)

        log_queries = diagnostic.split("Bound the log query", 1)[1]
        self.assertIn(
            'jsonPayload.event=\\"spooky_provider_failure\\"', log_queries
        )
        self.assertIn(
            "--format='table(timestamp,resource.labels.revision_name,"
            "jsonPayload.request_id,jsonPayload.failure_source,"
            "jsonPayload.failure_category,jsonPayload.upstream_status)'",
            log_queries,
        )
        self.assertIn(
            "--format='table(timestamp,resource.labels.revision_name,"
            "httpRequest.status,httpRequest.latency,trace)'",
            log_queries,
        )
        self.assertNotIn("--format=json", log_queries)
        self.assertNotIn("jsonPayload.message", log_queries)
        self.assertNotIn("textPayload", log_queries)
        self.assertNotIn("protoPayload", log_queries)
        self.assertIn("Do not add an automatic application retry", diagnostic)

    def test_diagnostic_no_reproduction_path_requires_true_scale_to_zero(
        self,
    ) -> None:
        diagnostic = self.runbook.split(
            "## Diagnose a provider failure without moving traffic", 1
        )[1].split("## Open publicly", 1)[0]

        first_stage = diagnostic.index("The first-stage experiment")
        idle_resume = diagnostic.index("`active=0, idle=1`", first_stage)
        second_stage = diagnostic.index(
            "limited to two true scale-to-zero cycles", idle_resume
        )
        true_zero = diagnostic.index("`active=0` and `idle=0`", second_stage)
        first_cold_request = diagnostic.index(
            "exactly one authenticated tagged `POST /v1/chat`", true_zero
        )
        final_outcome = diagnostic.index(
            "not reproduced in four total diagnostic calls", first_cold_request
        )
        self.assertLess(first_stage, idle_resume)
        self.assertLess(idle_resume, second_stage)
        self.assertLess(second_stage, true_zero)
        self.assertLess(true_zero, first_cold_request)
        self.assertLess(first_cold_request, final_outcome)

        self.assertIn("limited to two true scale-to-zero cycles", diagnostic)
        self.assertIn("use Cloud Monitoring without invoking", diagnostic)
        self.assertIn("after the preceding request completed", diagnostic)
        self.assertIn("same aligned sample timestamp", diagnostic)
        self.assertIn("Separately\n  fresh zeroes", diagnostic)
        self.assertIn("mismatched timestamp", diagnostic)
        self.assertIn("ambiguous\n  interval", diagnostic)
        self.assertIn("samples every 60 seconds", diagnostic)
        self.assertIn("up to 120 seconds", diagnostic)
        self.assertIn("A missing\n  series", diagnostic)
        self.assertIn("stale sample", diagnostic)
        self.assertIn("about 15 minutes", diagnostic)
        self.assertIn("prior revision still has\n  100% traffic", diagnostic)
        self.assertIn("`provider-diag` revision still has 0%", diagnostic)
        self.assertIn("invoker IAM\n  check is enabled", diagnostic)
        self.assertIn("`allUsers` is absent", diagnostic)
        self.assertIn("Any drift ends the experiment", diagnostic)
        self.assertIn("Do not call\n  `/health` first", diagnostic)
        self.assertIn("run requests concurrently", diagnostic)
        self.assertIn("perform a load test", diagnostic)
        self.assertIn(
            "does not count toward the service-level maximum", diagnostic
        )
        self.assertIn(
            "If a corroborated cold request returns `200`, do not retry",
            diagnostic,
        )
        self.assertIn(
            "revision-scoped\n  Cloud Run system startup evidence", diagnostic
        )
        self.assertIn("startup timestamp and revision name", diagnostic)
        self.assertIn("call does not count as a cold-start result", diagnostic)
        cycle = diagnostic.split("fail-fast block", 1)[1].split("~~~zsh", 1)[
            1
        ].split("~~~", 1)[0]
        request_start = cycle.index("TASK_COLD_REQUEST_START=")
        request = cycle.index("TASK_COLD_STATUS=", request_start)
        curl = cycle.index("curl --silent", request)
        request_end = cycle.index("TASK_COLD_REQUEST_END=", curl)
        startup_filter = cycle.index("TASK_STARTUP_FILTER=", request_end)
        lower_bound = cycle.index(
            'timestamp>=\\"${TASK_COLD_REQUEST_START}\\"', startup_filter
        )
        upper_bound = cycle.index(
            'timestamp<=\\"${TASK_COLD_REQUEST_END}\\"', lower_bound
        )
        autoscaling = cycle.index(
            r'textPayload:\"Starting new instance. Reason: AUTOSCALING\"',
            upper_bound,
        )
        polling = cycle.index("for TASK_STARTUP_ATTEMPT in {1..12}", autoscaling)
        final_read = cycle.index(
            'TASK_STARTUP_ROWS="$(spooky_read_startup_rows)"',
            polling,
        )
        final_read = cycle.index(
            'TASK_STARTUP_ROWS="$(spooky_read_startup_rows)"',
            final_read + 1,
        )
        final_count = cycle.index(
            'test "$TASK_STARTUP_COUNT" = 1', final_read
        )
        success = cycle.index("cold-cycle=corroborated", final_count)
        self.assertLess(request_start, request)
        self.assertLess(request, curl)
        self.assertLess(curl, request_end)
        self.assertLess(request_end, startup_filter)
        self.assertLess(startup_filter, lower_bound)
        self.assertLess(lower_bound, upper_bound)
        self.assertLess(upper_bound, autoscaling)
        self.assertLess(autoscaling, polling)
        self.assertLess(polling, final_read)
        self.assertLess(final_read, final_count)
        self.assertLess(final_count, success)
        self.assertIn(
            "--format='value(timestamp,resource.labels.revision_name)'",
            cycle,
        )
        self.assertEqual(cycle.count("TASK_STARTUP_FILTER="), 1)
        self.assertNotIn("TASK_COLD_REQUEST_END=", cycle[request_end + 1 :])
        self.assertIn('test "$TASK_STARTUP_COUNT" = 1', cycle)
        self.assertNotIn("break", cycle)

        json_id = cycle.index("TASK_COLD_JSON_REQUEST_ID=", request_end)
        header_id = cycle.index("TASK_COLD_HEADER_REQUEST_ID=", json_id)
        nonempty_id = cycle.index(
            'test -n "$TASK_COLD_HEADER_REQUEST_ID"', header_id
        )
        equal_id = cycle.index(
            'test "$TASK_COLD_JSON_REQUEST_ID" = '
            '"$TASK_COLD_HEADER_REQUEST_ID"',
            nonempty_id,
        )
        status_case = cycle.index('case "$TASK_COLD_STATUS" in', equal_id)
        self.assertLess(json_id, header_id)
        self.assertLess(header_id, nonempty_id)
        self.assertLess(nonempty_id, equal_id)
        self.assertLess(equal_id, status_case)
        self.assertLess(status_case, startup_filter)
        self.assertEqual(cycle.count("curl --silent"), 1)
        self.assertNotIn("/health", cycle)
        self.assertIn('.url | endswith("#tool")', cycle)
        self.assertIn('.url | endswith("#skill")', cycle)
        self.assertIn('.error.code == "PROVIDER_UNAVAILABLE"', cycle)
        self.assertIn('.error.code == "REQUEST_TIMEOUT"', cycle)
        self.assertIn("leaves the prior revision at 100%", diagnostic)
        self.assertIn("Do not call the\nbehavior fixed", diagnostic)
        self.assertIn("explicitly accepts the residual risk", diagnostic)

    def test_diagnostic_cold_cycle_block_is_shell_portable(self) -> None:
        diagnostic = self.runbook.split(
            "## Diagnose a provider failure without moving traffic", 1
        )[1].split("## Open publicly", 1)[0]
        cycle = diagnostic.split("fail-fast block", 1)[1].split(
            "~~~zsh", 1
        )[1].split("~~~", 1)[0]

        for shell in ("bash", "zsh"):
            with self.subTest(shell=shell):
                completed = subprocess.run(
                    [shell, "-n"],
                    input=cycle,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0)
                self.assertEqual(completed.stderr, "")

    def test_diagnostic_request_budget_and_stop_rules_are_global(self) -> None:
        diagnostic = self.runbook.split(
            "## Diagnose a provider failure without moving traffic", 1
        )[1].split("## Open publicly", 1)[0]

        budget = diagnostic.index("one global request budget")
        success_budget = diagnostic.index("exactly four chat calls", budget)
        absolute_budget = diagnostic.index("limited to five chat calls", budget)
        single_retry = diagnostic.index("only immediate manual retry", budget)
        first_stage_stop = diagnostic.index(
            "Any non-`200` first-stage response", single_retry
        )
        other_failures = diagnostic.index(
            "curl/auth/transport failure", first_stage_stop
        )
        self.assertLess(budget, success_budget)
        self.assertLess(success_budget, absolute_budget)
        self.assertLess(absolute_budget, single_retry)
        self.assertLess(single_retry, first_stage_stop)
        self.assertLess(first_stage_stop, other_failures)
        self.assertIn("immediately follow the failed call", diagnostic)
        self.assertIn("Then stop, even if the\nretry succeeds", diagnostic)
        self.assertIn("prohibits\nthe second stage", diagnostic)
        self.assertIn("malformed response envelope", diagnostic)
        self.assertIn("request-ID mismatch", diagnostic)
        self.assertIn("monitoring ambiguity", diagnostic)
        self.assertIn("must not be retried", diagnostic)

    def test_diagnostic_finalization_is_fail_closed_and_ordered(self) -> None:
        diagnostic = self.runbook.split(
            "## Diagnose a provider failure without moving traffic", 1
        )[1].split("## Open publicly", 1)[0]
        finalizer = diagnostic.split("spooky_final_cleanup()", 1)[1]

        cleanup_trap = finalizer.index("trap spooky_final_cleanup EXIT")
        precheck = finalizer.index('> "$TASK_FINAL_BEFORE"', cleanup_trap)
        precheck_private = finalizer.index(
            'index("allUsers") == null', precheck
        )
        exit_trap = finalizer.index("trap spooky_final_exit EXIT", precheck)
        mutation = finalizer.index("--remove-tags provider-diag", exit_trap)
        postcheck = finalizer.index("spooky_final_verify_closed", mutation)
        success = finalizer.index("diagnostic-finalization=passed", postcheck)
        self.assertLess(cleanup_trap, precheck)
        self.assertLess(precheck, precheck_private)
        self.assertLess(precheck_private, exit_trap)
        self.assertLess(exit_trap, mutation)
        self.assertLess(mutation, postcheck)
        self.assertLess(postcheck, success)

        verifier = diagnostic.split("spooky_final_verify_closed()", 1)[1].split(
            "spooky_final_recover()", 1
        )[0]
        self.assertIn('.tag == "provider-diag"', verifier)
        self.assertIn("length == 0", verifier)
        self.assertIn(".revisionName == $diagnostic", verifier)
        self.assertIn("invoker-iam-disabled", verifier)
        self.assertIn('index("allUsers") == null', verifier)

        recovery = diagnostic.split("spooky_final_recover()", 1)[1].split(
            "spooky_final_exit()", 1
        )[0]
        private = recovery.index("--invoker-iam-check")
        prior = recovery.index("--to-revisions", private)
        remove_tag = recovery.index("--remove-tags provider-diag", prior)
        verify = recovery.index("spooky_final_verify_closed", remove_tag)
        self.assertLess(private, prior)
        self.assertLess(prior, remove_tag)
        self.assertLess(remove_tag, verify)

        exit_handler = diagnostic.split("spooky_final_exit()", 1)[1].split(
            'gcloud run services describe "$TASK_SERVICE"', 1
        )[0]
        self.assertIn('local exit_status="$?"', exit_handler)
        self.assertIn("spooky_final_recover || true", exit_handler)
        self.assertIn('exit "$exit_status"', exit_handler)

    def test_diagnostic_finalization_block_is_shell_portable(self) -> None:
        diagnostic = self.runbook.split(
            "## Diagnose a provider failure without moving traffic", 1
        )[1].split("## Open publicly", 1)[0]
        finalization = diagnostic.split("fail-closed finalization gate", 1)[
            1
        ].split("~~~zsh", 1)[1].split("~~~", 1)[0]

        for shell in ("bash", "zsh"):
            with self.subTest(shell=shell):
                completed = subprocess.run(
                    [shell, "-n"],
                    input=finalization,
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0)
                self.assertEqual(completed.stderr, "")

    def test_diagnostic_finalization_exit_preserves_failure(self) -> None:
        probe = r'''
(
  set -euo pipefail
  spooky_final_recover() { printf 'final-recovery-called\n'; }
  spooky_final_cleanup() { printf 'final-cleanup-called\n'; }
  spooky_final_exit() {
    local exit_status="$?"
    trap - EXIT
    if (( exit_status != 0 )); then
      spooky_final_recover || true
    fi
    spooky_final_cleanup
    exit "$exit_status"
  }
  trap spooky_final_exit EXIT
  false
)
'''
        for shell in ("bash", "zsh"):
            with self.subTest(shell=shell):
                completed = subprocess.run(
                    [shell, "-c", probe],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 1)
                self.assertEqual(
                    completed.stdout.splitlines(),
                    ["final-recovery-called", "final-cleanup-called"],
                )
                self.assertEqual(completed.stderr, "")

    def test_diagnostic_exit_trap_is_portable_and_preserves_failure(self) -> None:
        probe = r'''
(
  set -euo pipefail
  recover() { printf 'recovery-called\n'; }
  cleanup() { printf 'cleanup-called\n'; }
  on_exit() {
    local exit_status="$?"
    trap - EXIT
    if (( exit_status != 0 )); then
      recover || true
    fi
    cleanup
    exit "$exit_status"
  }
  trap on_exit EXIT
  false
)
'''
        for shell in ("bash", "zsh"):
            with self.subTest(shell=shell):
                completed = subprocess.run(
                    [shell, "-c", probe],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 1)
                self.assertEqual(
                    completed.stdout.splitlines(),
                    ["recovery-called", "cleanup-called"],
                )
                self.assertEqual(completed.stderr, "")

    def test_runbook_checks_the_regional_default_build_identity(self) -> None:
        preflight = self.runbook.split("## Cloud Shell preflight", 1)[1].split(
            "Before building", 1
        )[0]
        self.assertIn("gcloud builds get-default-service-account", preflight)
        self.assertIn('--region "$TASK_REGION"', preflight)

    def test_runbook_makes_rollback_private_before_shifting_traffic(self) -> None:
        rollback = self.runbook.split(
            "### Roll back to a previously verified revision", 1
        )[1].split("### Return traffic", 1)[0]
        private_gate = rollback.index("--invoker-iam-check")
        traffic_shift = rollback.index("--to-revisions")
        authenticated_checks = rollback.index("authenticated health")
        public_gate = rollback.index("--no-invoker-iam-check")
        self.assertLess(private_gate, traffic_shift)
        self.assertLess(traffic_shift, authenticated_checks)
        self.assertLess(authenticated_checks, public_gate)

    def test_runbook_removes_task_owned_build_role_conditionally(self) -> None:
        teardown = self.runbook.split("### Complete teardown", 1)[1]
        self.assertIn(
            "only if this task added the binding and no other workload needs it",
            teardown,
        )
        self.assertIn("project-scoped budget alert", teardown)
        self.assertIn("source-staging objects or buckets", teardown)
        self.assertIn("provider retention policy", teardown)

    def test_private_and_public_verification_blocks_fail_closed(self) -> None:
        private = self.runbook.split(
            "Run one authenticated health check", 1
        )[1].split("Require HTTP 200", 1)[0]
        public = self.runbook.split(
            "execute the success-envelope", 1
        )[1].split("Record only the safe verification facts", 1)[0]

        for label, block, success_marker in (
            ("private", private, "private-verification=passed"),
            ("public", public, "public-verification=passed"),
        ):
            with self.subTest(label=label):
                fail_fast = block.index("set -euo pipefail")
                cleanup = block.index(f"trap spooky_{label}_cleanup EXIT")
                first_request = block.index("curl --fail-with-body")
                success = block.index(success_marker)
                guarded_block_end = block.rindex("\n)")
                self.assertLess(fail_fast, cleanup)
                self.assertLess(cleanup, first_request)
                self.assertLess(first_request, success)
                self.assertLess(success, guarded_block_end)
                self.assertIn("Do not", block)
                self.assertNotIn("/tmp/spooky-*", block)

        private_final_assertion = private.index(
            'test "$TASK_PRIVATE_JSON_REQUEST_ID" = '
            '"$TASK_PRIVATE_HEADER_REQUEST_ID"'
        )
        self.assertLess(
            private_final_assertion,
            private.index("private-verification=passed"),
        )

        public_no_credentials_assertion = public.index(
            "Unexpected CORS credentials support"
        )
        public_no_credentials_end = public.index(
            "\n  fi", public_no_credentials_assertion
        )
        self.assertLess(
            public_no_credentials_end,
            public.index("public-verification=passed"),
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from pathlib import Path
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

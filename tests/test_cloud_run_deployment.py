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


if __name__ == "__main__":
    unittest.main()

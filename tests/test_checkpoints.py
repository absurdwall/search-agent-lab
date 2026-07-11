from __future__ import annotations

import textwrap
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from search_agent_lab.checkpoints import (
    CHECKPOINTS,
    CHECKPOINT_ID_SECTION,
    CHECKPOINT_SECTION,
    CODENAME_SECTION,
    HONOR_CONFIRMATION,
    HONOR_SECTION,
    ISSUE_TEMPLATE_FILENAME,
    STATUS_COMMENT_MARKER,
    WEEK_01,
    CheckpointDefinition,
    EvidenceValidationError,
    UnknownCheckpointError,
    build_issue_form_url,
    canonicalize_evidence,
    codename_seed,
    evidence_fingerprint,
    expected_evidence,
    generate_codename,
    get_checkpoint,
    is_status_comment,
    parse_issue_submission,
    validate_issue_submission,
)


def issue_body_for(
    checkpoint: CheckpointDefinition,
    username: str,
    *,
    checkpoint_id: str | None = None,
    phrase: str | None = None,
    codename: str | None = None,
    checked: bool = True,
) -> str:
    checkbox = "x" if checked else " "
    return textwrap.dedent(
        f"""\
        ### {CHECKPOINT_ID_SECTION}

        {checkpoint_id or checkpoint.checkpoint_id}

        ### {CHECKPOINT_SECTION}

        {phrase or checkpoint.phrase}

        ### {CODENAME_SECTION}

        {codename or generate_codename(username, checkpoint)}

        ### {HONOR_SECTION}

        - [{checkbox}] {HONOR_CONFIRMATION}
        """
    )


class CatalogTests(unittest.TestCase):
    def test_week_1_catalog_lookup(self) -> None:
        self.assertIs(get_checkpoint(WEEK_01.checkpoint_id), WEEK_01)

    def test_unknown_checkpoint_id(self) -> None:
        with self.assertRaises(UnknownCheckpointError):
            get_checkpoint("week-99:not-real")

    def test_week_1_v1_mappings_are_locked(self) -> None:
        expected = {
            "absurdwall": "🟣 Violet Dolphin — Agent Trailblazer",
            "octocat": "🔴 Crimson Otter — Agent Investigator",
            "a": "🔵 Azure Falcon — Agent Pathfinder",
        }
        for username, codename in expected.items():
            with self.subTest(username=username):
                self.assertEqual(
                    generate_codename(username, WEEK_01),
                    codename,
                )


class EvidenceTests(unittest.TestCase):
    def test_week_1_expected_evidence_and_canonical_form(self) -> None:
        evidence = expected_evidence(WEEK_01)
        self.assertEqual(
            evidence,
            {
                "tool": "lookup_lab_status",
                "status": "ready",
                "topic": "google-adk",
                "summary": "The deterministic local tool completed.",
            },
        )
        self.assertEqual(
            canonicalize_evidence(evidence, WEEK_01),
            "lookup_lab_status|ready|google-adk|"
            "The deterministic local tool completed.",
        )

    def test_evidence_fingerprint_is_stable_and_in_seed(self) -> None:
        evidence = {
            **expected_evidence(WEEK_01),
            "ignored_runtime_detail": "not hashed",
        }
        fingerprint = evidence_fingerprint(evidence, WEEK_01)
        self.assertEqual(
            fingerprint,
            "17060e3f04638ae68ad69932216d020fc4e8fdca46693daa467f7d55d4d4dd91",
        )
        spaced_evidence = {
            **expected_evidence(WEEK_01),
            "summary": "  The deterministic  local tool completed.  ",
        }
        self.assertEqual(
            evidence_fingerprint(spaced_evidence, WEEK_01),
            fingerprint,
        )
        self.assertEqual(
            codename_seed("AbsurdWall", WEEK_01, evidence),
            "search-agent-lab:week-01:first-tool-found:absurdwall:"
            f"{fingerprint}:v1",
        )

    def test_incomplete_or_changed_evidence_is_rejected(self) -> None:
        incomplete = expected_evidence(WEEK_01)
        incomplete.pop("summary")
        changed = {**expected_evidence(WEEK_01), "status": "unknown"}
        for evidence in (incomplete, changed):
            with self.subTest(evidence=evidence):
                with self.assertRaises(EvidenceValidationError):
                    generate_codename("absurdwall", WEEK_01, evidence)


class GenericIssueTests(unittest.TestCase):
    def test_generic_url_prefills_all_checkpoint_fields(self) -> None:
        query = parse_qs(
            urlparse(build_issue_form_url("absurdwall", WEEK_01)).query
        )
        self.assertEqual(query["template"], [ISSUE_TEMPLATE_FILENAME])
        self.assertEqual(query["title"], [WEEK_01.issue_title])
        self.assertEqual(
            query["checkpoint_id"],
            [WEEK_01.checkpoint_id],
        )
        self.assertEqual(query["checkpoint"], [WEEK_01.phrase])
        self.assertEqual(
            query["codename"],
            [generate_codename("absurdwall", WEEK_01)],
        )

    def test_generic_issue_form_parsing(self) -> None:
        submission = parse_issue_submission(
            issue_body_for(WEEK_01, "absurdwall")
        )
        self.assertEqual(submission.checkpoint_id, WEEK_01.checkpoint_id)
        self.assertEqual(submission.checkpoint, WEEK_01.phrase)
        self.assertEqual(
            submission.codename,
            generate_codename("absurdwall", WEEK_01),
        )
        self.assertTrue(submission.honor_confirmed)

    def test_actual_author_validation(self) -> None:
        body = issue_body_for(WEEK_01, "absurdwall")
        valid = validate_issue_submission("AbsurdWall", body)
        invalid = validate_issue_submission("octocat", body)
        self.assertTrue(valid.valid)
        self.assertFalse(invalid.valid)
        self.assertIn(
            "The codename does not match the actual issue author.",
            invalid.errors,
        )

    def test_invalid_fields_remain_helpful_and_static(self) -> None:
        body = issue_body_for(
            WEEK_01,
            "absurdwall",
            phrase="changed",
            codename="$(touch never-run)",
            checked=False,
        )
        result = validate_issue_submission("absurdwall", body)
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 3)
        self.assertNotIn("$(touch never-run)", result.comment())

    def test_unknown_checkpoint_submission_is_invalid(self) -> None:
        body = issue_body_for(
            WEEK_01,
            "absurdwall",
            checkpoint_id="week-99:not-real",
        )
        result = validate_issue_submission("absurdwall", body)
        self.assertTrue(result.applicable)
        self.assertFalse(result.valid)
        self.assertEqual(result.checkpoint, None)
        self.assertEqual(
            result.errors,
            ("The checkpoint ID is missing or unknown.",),
        )

    def test_unrelated_bot_authored_issue_is_ignored(self) -> None:
        result = validate_issue_submission(
            "dependabot[bot]",
            "### Dependency update\n\nRoutine maintenance.",
            title="Bump a dependency",
        )
        self.assertFalse(result.applicable)
        self.assertEqual(result.comment(), "")

    def test_checkpoint_from_unsupported_author_is_safely_invalid(self) -> None:
        result = validate_issue_submission(
            "dependabot[bot]",
            issue_body_for(WEEK_01, "absurdwall"),
        )
        self.assertTrue(result.applicable)
        self.assertFalse(result.valid)
        self.assertEqual(result.normalized_username, "")
        self.assertNotIn("dependabot[bot]", result.comment())

    def test_status_comment_marker_requires_bot_author(self) -> None:
        result = validate_issue_submission(
            "absurdwall",
            issue_body_for(WEEK_01, "absurdwall"),
        )
        self.assertEqual(result.comment().count(STATUS_COMMENT_MARKER), 1)
        self.assertTrue(
            is_status_comment(result.comment(), "github-actions[bot]")
        )
        self.assertFalse(is_status_comment(result.comment(), "learner"))

    def test_future_catalog_definition_uses_same_core(self) -> None:
        future = CheckpointDefinition(
            checkpoint_id="week-02:second-tool",
            phrase="Week 2 — Second tool found",
            achievement_message="🎉 Another tool!",
            codename_version="v1",
            issue_title="[Week 2 checkpoint] Second tool found",
            expected_evidence=(
                ("tool", "lookup_second_status"),
                ("status", "ready"),
                ("topic", "week-02"),
                ("summary", "The second deterministic tool completed."),
            ),
            checkpoint_label="week-02",
        )
        with patch.dict(CHECKPOINTS, {future.checkpoint_id: future}):
            body = issue_body_for(future, "octocat")
            result = validate_issue_submission("octocat", body)
            url = build_issue_form_url("octocat", future.checkpoint_id)
        self.assertTrue(result.valid)
        self.assertEqual(result.checkpoint, future)
        self.assertEqual(
            parse_qs(urlparse(url).query)["checkpoint_id"],
            [future.checkpoint_id],
        )


if __name__ == "__main__":
    unittest.main()

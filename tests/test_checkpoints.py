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
    UnknownCheckpointError,
    build_issue_form_url,
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

    def test_week_1_fixed_mappings_are_preserved(self) -> None:
        expected = {
            "absurdwall": "🟢 Emerald Owl — Agent Explorer",
            "octocat": "🟢 Emerald Gecko — Agent Navigator",
            "a": "🔴 Crimson Otter — Agent Tinkerer",
        }
        for username, codename in expected.items():
            with self.subTest(username=username):
                self.assertEqual(
                    generate_codename(username, WEEK_01),
                    codename,
                )


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

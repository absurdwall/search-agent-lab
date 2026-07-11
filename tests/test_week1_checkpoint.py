from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from search_agent_lab.week1_checkpoint import (
    CHECKPOINT_PHRASE,
    CODENAME_SECTION,
    HONOR_CONFIRMATION,
    HONOR_SECTION,
    ISSUE_TEMPLATE_FILENAME,
    CHECKPOINT_SECTION,
    build_issue_form_url,
    generate_codename,
    main,
    normalize_github_username,
    parse_codename_phrase,
    parse_issue_sections,
    validate_issue_submission,
)


def issue_body_for(
    username: str,
    *,
    codename: str | None = None,
    checkpoint: str = CHECKPOINT_PHRASE,
    checked: bool = True,
) -> str:
    checkbox = "x" if checked else " "
    return textwrap.dedent(
        f"""\
        ### {CHECKPOINT_SECTION}

        {checkpoint}

        ### {CODENAME_SECTION}

        {codename or generate_codename(username)}

        ### {HONOR_SECTION}

        - [{checkbox}] {HONOR_CONFIRMATION}
        """
    )


class UsernameNormalizationTests(unittest.TestCase):
    def test_normalizes_case_whitespace_and_at_prefix(self) -> None:
        self.assertEqual(
            normalize_github_username("  @Octo-Cat  "),
            "octo-cat",
        )

    def test_rejects_non_github_username_characters(self) -> None:
        for value in ("github_user", "-octocat", "octocat-", "two--hyphens"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    normalize_github_username(value)


class CodenameTests(unittest.TestCase):
    def test_fixed_username_mappings(self) -> None:
        expected = {
            "absurdwall": "🟢 Emerald Owl — Agent Explorer",
            "octocat": "🟢 Emerald Gecko — Agent Navigator",
            "a": "🔴 Crimson Otter — Agent Tinkerer",
        }
        for username, codename in expected.items():
            with self.subTest(username=username):
                self.assertEqual(generate_codename(username), codename)

    def test_phrase_parser_accepts_only_canonical_shape(self) -> None:
        parsed = parse_codename_phrase(
            "  🟢   Emerald  Owl — Agent   Explorer  "
        )
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(
            parsed.phrase,
            "🟢 Emerald Owl — Agent Explorer",
        )
        self.assertIsNone(
            parse_codename_phrase("🟢 Emerald Owl - Agent Explorer")
        )

    def test_prefilled_issue_url_uses_form_field_ids(self) -> None:
        url = build_issue_form_url("absurdwall")
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        self.assertEqual(
            parsed.path,
            "/absurdwall/search-agent-lab/issues/new",
        )
        self.assertEqual(
            query["template"],
            [ISSUE_TEMPLATE_FILENAME],
        )
        self.assertEqual(query["checkpoint"], [CHECKPOINT_PHRASE])
        self.assertEqual(
            query["codename"],
            [generate_codename("absurdwall")],
        )


class IssueSubmissionTests(unittest.TestCase):
    def test_parses_issue_form_sections(self) -> None:
        body = issue_body_for("absurdwall")
        sections = parse_issue_sections(body)
        self.assertEqual(
            sections[CHECKPOINT_SECTION],
            CHECKPOINT_PHRASE,
        )
        self.assertEqual(
            sections[CODENAME_SECTION],
            generate_codename("absurdwall"),
        )
        self.assertIn(HONOR_CONFIRMATION, sections[HONOR_SECTION])

    def test_valid_submission_uses_actual_issue_author(self) -> None:
        result = validate_issue_submission(
            "AbsurdWall",
            issue_body_for("absurdwall"),
        )
        self.assertTrue(result.applicable)
        self.assertTrue(result.valid)
        self.assertEqual(result.errors, ())

    def test_wrong_author_codename_is_invalid(self) -> None:
        result = validate_issue_submission(
            "octocat",
            issue_body_for(
                "octocat",
                codename=generate_codename("absurdwall"),
            ),
        )
        self.assertTrue(result.applicable)
        self.assertFalse(result.valid)
        self.assertIn(
            "The codename does not match the actual issue author.",
            result.errors,
        )

    def test_changed_phrase_and_unchecked_honor_are_invalid(self) -> None:
        result = validate_issue_submission(
            "absurdwall",
            issue_body_for(
                "absurdwall",
                checkpoint="Week 1 complete",
                checked=False,
            ),
        )
        self.assertTrue(result.applicable)
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 2)

    def test_unrelated_issue_is_not_applicable(self) -> None:
        result = validate_issue_submission(
            "octocat",
            "### Bug report\n\nSomething happened.",
            title="A normal issue",
        )
        self.assertFalse(result.applicable)
        self.assertFalse(result.valid)
        self.assertEqual(result.comment(), "")

    def test_checkpoint_label_keeps_edited_issue_applicable(self) -> None:
        result = validate_issue_submission(
            "octocat",
            "The learner is still editing this submission.",
            title="Edited title",
            labels=("week-1-checkpoint",),
        )
        self.assertTrue(result.applicable)
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 3)

    def test_untrusted_issue_text_is_not_reflected_in_comment(self) -> None:
        untrusted_text = "$(touch should-never-run)"
        result = validate_issue_submission(
            "octocat",
            issue_body_for("octocat", codename=untrusted_text),
        )
        self.assertFalse(result.valid)
        self.assertNotIn(untrusted_text, result.comment())
        self.assertNotIn(untrusted_text, json.dumps(result.as_action_payload()))

    def test_action_cli_reads_issue_text_as_environment_data(self) -> None:
        body = issue_body_for("absurdwall")
        with tempfile.TemporaryDirectory() as temporary_directory:
            output = Path(temporary_directory) / "result.json"
            environment = {
                "TEST_ISSUE_BODY": body,
                "TEST_ISSUE_TITLE": "[Week 1 checkpoint] First tool found",
                "TEST_ISSUE_LABELS": json.dumps(["week-1-checkpoint"]),
            }
            with patch.dict(os.environ, environment, clear=False):
                return_code = main(
                    [
                        "validate-issue",
                        "--username",
                        "absurdwall",
                        "--body-env",
                        "TEST_ISSUE_BODY",
                        "--title-env",
                        "TEST_ISSUE_TITLE",
                        "--labels-env",
                        "TEST_ISSUE_LABELS",
                        "--output",
                        str(output),
                    ]
                )
            payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(return_code, 0)
        self.assertTrue(payload["applicable"])
        self.assertTrue(payload["valid"])
        self.assertNotIn("submitted_body", payload)


if __name__ == "__main__":
    unittest.main()

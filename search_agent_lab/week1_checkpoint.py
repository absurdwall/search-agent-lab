"""Deterministic Week 1 checkpoint helpers.

The notebook and GitHub workflow both import this module. Issue text is treated
only as data; no submitted content is evaluated or passed to a shell.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata
from urllib.parse import quote, urlencode


CODENAME_VERSION = "v1"
CHECKPOINT_PHRASE = "Week 1 — First tool found"
ACHIEVEMENT_MESSAGE = "🎉 The agent found its first tool!"
ISSUE_TEMPLATE_FILENAME = "week-1-checkpoint.yml"
ISSUE_TITLE_PREFIX = "[Week 1 checkpoint]"
DEFAULT_REPOSITORY = "absurdwall/search-agent-lab"

CHECKPOINT_SECTION = "Checkpoint"
CODENAME_SECTION = "Agent codename"
HONOR_SECTION = "Honor-system confirmation"
HONOR_CONFIRMATION = (
    "I completed the optional live checkpoint and am sharing only the "
    "generated public codename."
)

BASE_LABEL = "week-1-checkpoint"
PASSED_LABEL = "week-1-passed"
NEEDS_FIX_LABEL = "week-1-needs-fix"

# Versioned, repository-local source lists. Changing these values requires a
# new codename version so existing submissions remain reproducible.
COLOR_BADGES_V1: tuple[tuple[str, str], ...] = (
    ("🔴", "Crimson"),
    ("🟠", "Amber"),
    ("🟡", "Golden"),
    ("🟢", "Emerald"),
    ("🔵", "Azure"),
    ("🟣", "Violet"),
    ("🩷", "Coral"),
    ("⚪", "Silver"),
)

ANIMALS_V1: tuple[str, ...] = (
    "Badger",
    "Dolphin",
    "Falcon",
    "Fox",
    "Gecko",
    "Hare",
    "Lynx",
    "Otter",
    "Owl",
    "Panda",
    "Raven",
    "Tiger",
)

TITLES_V1: tuple[str, ...] = (
    "Builder",
    "Cartographer",
    "Catalyst",
    "Explorer",
    "Investigator",
    "Navigator",
    "Pathfinder",
    "Scout",
    "Tinkerer",
    "Toolsmith",
    "Trailblazer",
    "Wayfinder",
)

_USERNAME_RE = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$"
)
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SECTION_RE = re.compile(r"(?m)^###\s+(.+?)\s*$")
_CODENAME_RE = re.compile(
    r"^(?P<emoji>\S+)\s+"
    r"(?P<color>[A-Za-z]+)\s+"
    r"(?P<animal>[A-Za-z]+)\s+"
    r"—\s+Agent\s+"
    r"(?P<title>[A-Za-z]+)$"
)


@dataclass(frozen=True)
class CodenameParts:
    emoji: str
    color: str
    animal: str
    title: str

    @property
    def phrase(self) -> str:
        return (
            f"{self.emoji} {self.color} {self.animal} — "
            f"Agent {self.title}"
        )


@dataclass(frozen=True)
class IssueSubmission:
    checkpoint: str
    codename: str
    honor_confirmed: bool


@dataclass(frozen=True)
class ValidationResult:
    applicable: bool
    valid: bool
    normalized_username: str
    expected_codename: str
    errors: tuple[str, ...]

    def comment(self) -> str:
        if not self.applicable:
            return ""
        if self.valid:
            return (
                f"{ACHIEVEMENT_MESSAGE}\n\n"
                f"Checkpoint passed for @{self.normalized_username}. "
                f"Your Week 1 codename is **{self.expected_codename}**.\n\n"
                "This is an optional public honor-system celebration, "
                "not authentication or formal grading."
            )

        error_lines = "\n".join(f"- {error}" for error in self.errors)
        return (
            "Almost there — please edit this issue and try again.\n\n"
            f"Expected codename for @{self.normalized_username}: "
            f"**{self.expected_codename}**\n\n"
            f"{error_lines}\n\n"
            "Keep the checkpoint phrase unchanged, paste the exact codename, "
            "and check the honor-system confirmation. This workflow will "
            "revalidate the issue after an edit or reopen."
        )

    def as_action_payload(self) -> dict[str, object]:
        return {
            "applicable": self.applicable,
            "valid": self.valid,
            "normalized_username": self.normalized_username,
            "expected_codename": self.expected_codename,
            "errors": list(self.errors),
            "comment": self.comment(),
        }


def normalize_github_username(value: str) -> str:
    """Normalize and validate a public GitHub login."""
    if not isinstance(value, str):
        raise ValueError("GitHub username must be text.")

    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    if normalized.startswith("@"):
        normalized = normalized[1:]

    if (
        not _USERNAME_RE.fullmatch(normalized)
        or "--" in normalized
    ):
        raise ValueError(
            "Enter a GitHub username using 1–39 letters, numbers, or "
            "single hyphens."
        )
    return normalized


def codename_seed(username: str) -> str:
    normalized = normalize_github_username(username)
    return (
        "search-agent-lab:week-01:first-tool-found:"
        f"{normalized}:{CODENAME_VERSION}"
    )


def generate_codename(username: str) -> str:
    """Generate a deterministic Week 1 codename for a GitHub username."""
    digest = hashlib.sha256(
        codename_seed(username).encode("utf-8")
    ).digest()

    color_index = int.from_bytes(digest[0:8], "big") % len(COLOR_BADGES_V1)
    animal_index = int.from_bytes(digest[8:16], "big") % len(ANIMALS_V1)
    title_index = int.from_bytes(digest[16:24], "big") % len(TITLES_V1)

    emoji, color = COLOR_BADGES_V1[color_index]
    parts = CodenameParts(
        emoji=emoji,
        color=color,
        animal=ANIMALS_V1[animal_index],
        title=TITLES_V1[title_index],
    )
    return parts.phrase


def normalize_phrase(value: str) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).split())


def parse_codename_phrase(value: str) -> CodenameParts | None:
    """Parse the public codename format without evaluating any input."""
    match = _CODENAME_RE.fullmatch(normalize_phrase(value))
    if not match:
        return None
    return CodenameParts(**match.groupdict())


def parse_issue_sections(body: str) -> dict[str, str]:
    """Parse GitHub Issue Form markdown headings into plain text sections."""
    if not isinstance(body, str):
        return {}

    normalized_body = body.replace("\r\n", "\n").replace("\r", "\n")
    matches = list(_SECTION_RE.finditer(normalized_body))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        label = normalize_phrase(match.group(1))
        start = match.end()
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(normalized_body)
        )
        value = normalized_body[start:end].strip()
        if label in sections:
            sections[label] = f"{sections[label]}\n{value}".strip()
        else:
            sections[label] = value
    return sections


def parse_issue_submission(body: str) -> IssueSubmission:
    sections = parse_issue_sections(body)
    honor_lines = sections.get(HONOR_SECTION, "").splitlines()
    honor_confirmed = any(
        re.fullmatch(
            rf"- \[[xX]\] {re.escape(HONOR_CONFIRMATION)}",
            line.strip(),
        )
        for line in honor_lines
    )
    return IssueSubmission(
        checkpoint=normalize_phrase(
            sections.get(CHECKPOINT_SECTION, "")
        ),
        codename=normalize_phrase(sections.get(CODENAME_SECTION, "")),
        honor_confirmed=honor_confirmed,
    )


def validate_issue_submission(
    username: str,
    body: str,
    *,
    title: str = "",
    labels: tuple[str, ...] = (),
) -> ValidationResult:
    """Validate a submission against the actual issue author's login."""
    normalized_username = normalize_github_username(username)
    expected_codename = generate_codename(normalized_username)
    sections = parse_issue_sections(body)
    normalized_labels = {normalize_phrase(label) for label in labels}
    applicable = (
        CHECKPOINT_SECTION in sections
        or normalize_phrase(title).startswith(ISSUE_TITLE_PREFIX)
        or BASE_LABEL in normalized_labels
    )
    if not applicable:
        return ValidationResult(
            applicable=False,
            valid=False,
            normalized_username=normalized_username,
            expected_codename=expected_codename,
            errors=(),
        )

    submission = parse_issue_submission(body)
    errors: list[str] = []
    if submission.checkpoint != CHECKPOINT_PHRASE:
        errors.append("The checkpoint phrase is missing or changed.")

    parsed_codename = parse_codename_phrase(submission.codename)
    if (
        parsed_codename is None
        or parsed_codename.phrase != expected_codename
    ):
        errors.append(
            "The codename does not match the actual issue author."
        )

    if not submission.honor_confirmed:
        errors.append("The honor-system confirmation is not checked.")

    return ValidationResult(
        applicable=True,
        valid=not errors,
        normalized_username=normalized_username,
        expected_codename=expected_codename,
        errors=tuple(errors),
    )


def build_issue_form_url(
    username: str,
    *,
    repository: str = DEFAULT_REPOSITORY,
) -> str:
    """Build a prefilled public Issue Form URL for a successful checkpoint."""
    if not _REPOSITORY_RE.fullmatch(repository):
        raise ValueError("Repository must use the OWNER/REPO format.")

    params = (
        ("template", ISSUE_TEMPLATE_FILENAME),
        ("title", f"{ISSUE_TITLE_PREFIX} First tool found"),
        ("checkpoint", CHECKPOINT_PHRASE),
        ("codename", generate_codename(username)),
    )
    return (
        f"https://github.com/{repository}/issues/new?"
        f"{urlencode(params, quote_via=quote)}"
    )


def _labels_from_environment(variable_name: str) -> tuple[str, ...]:
    raw_value = os.environ.get(variable_name, "[]")
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(value for value in parsed if isinstance(value, str))


def _write_action_result(
    *,
    username: str,
    body_environment: str,
    title_environment: str,
    labels_environment: str,
    output: Path,
) -> None:
    result = validate_issue_submission(
        username=username,
        body=os.environ.get(body_environment, ""),
        title=os.environ.get(title_environment, ""),
        labels=_labels_from_environment(labels_environment),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            result.as_action_payload(),
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Week 1 checkpoint utilities."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser(
        "validate-issue",
        help="Validate Issue Form text supplied through environment variables.",
    )
    validate_parser.add_argument("--username", required=True)
    validate_parser.add_argument("--body-env", required=True)
    validate_parser.add_argument("--title-env", required=True)
    validate_parser.add_argument("--labels-env", required=True)
    validate_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "validate-issue":
        _write_action_result(
            username=args.username,
            body_environment=args.body_env,
            title_environment=args.title_env,
            labels_environment=args.labels_env,
            output=args.output,
        )
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

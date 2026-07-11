"""Reusable deterministic checkpoint engine.

Issue text is untrusted data. It is parsed as plain text, never evaluated, and
never copied into executable workflow source or status comments.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata
from urllib.parse import quote, urlencode

from .catalog import (
    CHECKPOINTS,
    DEFAULT_CHECKPOINT_ID,
    CheckpointDefinition,
    UnknownCheckpointError,
    resolve_checkpoint,
)
from .words import WORD_LISTS


ISSUE_TEMPLATE_FILENAME = "checkpoint.yml"
DEFAULT_REPOSITORY = "absurdwall/search-agent-lab"

CHECKPOINT_ID_SECTION = "Checkpoint ID"
CHECKPOINT_SECTION = "Checkpoint"
CODENAME_SECTION = "Agent codename"
HONOR_SECTION = "Honor-system confirmation"
HONOR_CONFIRMATION = (
    "I completed the optional live checkpoint and am sharing only the "
    "generated public codename."
)

BASE_LABEL = "checkpoint"
PASSED_LABEL = "passed"
NEEDS_FIX_LABEL = "needs-fix"
STATUS_COMMENT_MARKER = "<!-- search-agent-lab-checkpoint-status -->"

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


class EvidenceValidationError(ValueError):
    """Raised when observed evidence differs from the public catalog."""


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
    checkpoint_id: str
    checkpoint: str
    codename: str
    honor_confirmed: bool


@dataclass(frozen=True)
class ValidationResult:
    applicable: bool
    valid: bool
    normalized_username: str
    checkpoint: CheckpointDefinition | None
    expected_codename: str
    errors: tuple[str, ...]

    def comment(self) -> str:
        """Return the single safe status comment body used by the Action."""
        if not self.applicable:
            return ""

        if self.valid and self.checkpoint is not None:
            return (
                f"{STATUS_COMMENT_MARKER}\n"
                f"{self.checkpoint.achievement_message}\n\n"
                f"Checkpoint passed for @{self.normalized_username}. "
                f"Your codename is **{self.expected_codename}**.\n\n"
                "This is an optional public honor-system celebration, "
                "not authentication or formal grading."
            )

        error_lines = "\n".join(f"- {error}" for error in self.errors)
        expected_line = (
            f"\n\nExpected codename for @{self.normalized_username}: "
            f"**{self.expected_codename}**"
            if self.expected_codename
            else ""
        )
        return (
            f"{STATUS_COMMENT_MARKER}\n"
            "Almost there — please edit this issue and try again."
            f"{expected_line}\n\n"
            f"{error_lines}\n\n"
            "Keep the checkpoint fields unchanged, paste the exact codename, "
            "and check the honor-system confirmation. This workflow will "
            "revalidate the issue after an edit or reopen."
        )

    def as_action_payload(self) -> dict[str, object]:
        """Expose only catalog-derived or fixed data to the workflow."""
        return {
            "applicable": self.applicable,
            "valid": self.valid,
            "normalized_username": self.normalized_username,
            "checkpoint_id": (
                self.checkpoint.checkpoint_id if self.checkpoint else ""
            ),
            "checkpoint_label": (
                self.checkpoint.checkpoint_label if self.checkpoint else ""
            ),
            "expected_codename": self.expected_codename,
            "errors": list(self.errors),
            "comment": self.comment(),
            "comment_marker": STATUS_COMMENT_MARKER,
        }


def normalize_github_username(value: str) -> str:
    """Normalize and validate a public GitHub login."""
    if not isinstance(value, str):
        raise ValueError("GitHub username must be text.")

    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    if normalized.startswith("@"):
        normalized = normalized[1:]

    if not _USERNAME_RE.fullmatch(normalized) or "--" in normalized:
        raise ValueError(
            "Enter a GitHub username using 1–39 letters, numbers, or "
            "single hyphens."
        )
    return normalized


def expected_evidence(
    checkpoint: str | CheckpointDefinition = DEFAULT_CHECKPOINT_ID,
) -> dict[str, str]:
    """Return a copy of the checkpoint's public allowlisted evidence."""
    definition = resolve_checkpoint(checkpoint)
    return dict(definition.expected_evidence)


def _canonical_evidence_value(value: object) -> str:
    if not isinstance(value, str):
        raise EvidenceValidationError(
            "Checkpoint evidence is incomplete or changed."
        )
    return " ".join(unicodedata.normalize("NFKC", value).split())


def canonicalize_evidence(
    evidence: Mapping[str, object] | None = None,
    checkpoint: str | CheckpointDefinition = DEFAULT_CHECKPOINT_ID,
) -> str:
    """Validate and canonicalize only catalog-declared evidence fields."""
    definition = resolve_checkpoint(checkpoint)
    if not definition.expected_evidence:
        raise EvidenceValidationError(
            "Checkpoint does not define expected evidence."
        )

    supplied = (
        expected_evidence(definition)
        if evidence is None
        else evidence
    )
    canonical_values: list[str] = []
    for field, expected_value in definition.expected_evidence:
        actual = _canonical_evidence_value(supplied.get(field))
        expected = _canonical_evidence_value(expected_value)
        if actual != expected:
            raise EvidenceValidationError(
                "Checkpoint evidence is incomplete or changed."
            )
        canonical_values.append(actual)
    return "|".join(canonical_values)


def evidence_fingerprint(
    evidence: Mapping[str, object] | None = None,
    checkpoint: str | CheckpointDefinition = DEFAULT_CHECKPOINT_ID,
) -> str:
    """Hash the stable allowlisted evidence, never a full runtime trace."""
    canonical = canonicalize_evidence(evidence, checkpoint)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def codename_seed(
    username: str,
    checkpoint: str | CheckpointDefinition = DEFAULT_CHECKPOINT_ID,
    evidence: Mapping[str, object] | None = None,
) -> str:
    definition = resolve_checkpoint(checkpoint)
    normalized = normalize_github_username(username)
    fingerprint = evidence_fingerprint(evidence, definition)
    return (
        f"search-agent-lab:{definition.checkpoint_id}:"
        f"{normalized}:{fingerprint}:{definition.codename_version}"
    )


def generate_codename(
    username: str,
    checkpoint: str | CheckpointDefinition = DEFAULT_CHECKPOINT_ID,
    evidence: Mapping[str, object] | None = None,
) -> str:
    """Generate a deterministic codename for a catalog checkpoint."""
    definition = resolve_checkpoint(checkpoint)
    try:
        words = WORD_LISTS[definition.codename_version]
    except KeyError as error:
        raise ValueError("Unknown codename word-list version.") from error

    digest = hashlib.sha256(
        codename_seed(username, definition, evidence).encode("utf-8")
    ).digest()
    color_index = int.from_bytes(digest[0:8], "big") % len(
        words.color_badges
    )
    animal_index = int.from_bytes(digest[8:16], "big") % len(
        words.animals
    )
    title_index = int.from_bytes(digest[16:24], "big") % len(
        words.titles
    )

    emoji, color = words.color_badges[color_index]
    return CodenameParts(
        emoji=emoji,
        color=color,
        animal=words.animals[animal_index],
        title=words.titles[title_index],
    ).phrase


def normalize_phrase(value: str) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(unicodedata.normalize("NFKC", value).split())


def parse_codename_phrase(value: str) -> CodenameParts | None:
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


def parse_issue_submission(
    body: str,
    *,
    default_checkpoint_id: str = "",
) -> IssueSubmission:
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
        checkpoint_id=normalize_phrase(
            sections.get(CHECKPOINT_ID_SECTION, default_checkpoint_id)
        ),
        checkpoint=normalize_phrase(
            sections.get(CHECKPOINT_SECTION, "")
        ),
        codename=normalize_phrase(sections.get(CODENAME_SECTION, "")),
        honor_confirmed=honor_confirmed,
    )


def _known_checkpoint_labels() -> set[str]:
    labels = {BASE_LABEL}
    for definition in CHECKPOINTS.values():
        if definition.checkpoint_label:
            labels.add(definition.checkpoint_label)
        labels.update(definition.legacy_labels)
    return labels


def _is_checkpoint_issue(
    sections: dict[str, str],
    title: str,
    labels: tuple[str, ...],
) -> bool:
    normalized_labels = {normalize_phrase(label) for label in labels}
    return (
        CHECKPOINT_ID_SECTION in sections
        or CHECKPOINT_SECTION in sections
        or normalize_phrase(title).startswith("[Checkpoint]")
        or bool(normalized_labels & _known_checkpoint_labels())
        or any(
            normalize_phrase(title).startswith(
                normalize_phrase(definition.issue_title)
            )
            for definition in CHECKPOINTS.values()
        )
    )


def _infer_legacy_checkpoint_id(
    title: str,
    labels: tuple[str, ...],
) -> str:
    """Recognize pre-refactor Week 1 issues without weakening new forms."""
    normalized_title = normalize_phrase(title)
    normalized_labels = {normalize_phrase(label) for label in labels}
    matches = [
        definition.checkpoint_id
        for definition in CHECKPOINTS.values()
        if normalized_title.startswith(normalize_phrase(definition.issue_title))
        or bool(normalized_labels & set(definition.legacy_labels))
    ]
    return matches[0] if len(matches) == 1 else ""


def validate_issue_submission(
    username: str,
    body: str,
    *,
    title: str = "",
    labels: tuple[str, ...] = (),
    default_checkpoint_id: str = "",
) -> ValidationResult:
    """Validate one issue against its actual author's public login."""
    sections = parse_issue_sections(body)
    applicable = _is_checkpoint_issue(sections, title, labels)
    if not applicable:
        return ValidationResult(
            applicable=False,
            valid=False,
            normalized_username="",
            checkpoint=None,
            expected_codename="",
            errors=(),
        )

    try:
        normalized_username = normalize_github_username(username)
    except ValueError:
        return ValidationResult(
            applicable=True,
            valid=False,
            normalized_username="",
            checkpoint=None,
            expected_codename="",
            errors=(
                "The issue author does not have a supported public "
                "GitHub username.",
            ),
        )

    submission = parse_issue_submission(
        body,
        default_checkpoint_id=(
            default_checkpoint_id
            or _infer_legacy_checkpoint_id(title, labels)
        ),
    )
    try:
        definition = resolve_checkpoint(submission.checkpoint_id)
    except UnknownCheckpointError:
        return ValidationResult(
            applicable=True,
            valid=False,
            normalized_username=normalized_username,
            checkpoint=None,
            expected_codename="",
            errors=("The checkpoint ID is missing or unknown.",),
        )

    expected_codename = generate_codename(
        normalized_username,
        definition,
    )
    errors: list[str] = []
    if submission.checkpoint != definition.phrase:
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
        checkpoint=definition,
        expected_codename=expected_codename,
        errors=tuple(errors),
    )


def build_issue_form_url(
    username: str,
    checkpoint: str | CheckpointDefinition = DEFAULT_CHECKPOINT_ID,
    evidence: Mapping[str, object] | None = None,
    *,
    repository: str = DEFAULT_REPOSITORY,
) -> str:
    """Build a prefilled public Issue Form URL for one checkpoint."""
    if not _REPOSITORY_RE.fullmatch(repository):
        raise ValueError("Repository must use the OWNER/REPO format.")
    definition = resolve_checkpoint(checkpoint)
    params = (
        ("template", ISSUE_TEMPLATE_FILENAME),
        ("title", definition.issue_title),
        ("checkpoint_id", definition.checkpoint_id),
        ("checkpoint", definition.phrase),
        ("codename", generate_codename(username, definition, evidence)),
    )
    return (
        f"https://github.com/{repository}/issues/new?"
        f"{urlencode(params, quote_via=quote)}"
    )


def is_status_comment(body: str, author_login: str) -> bool:
    """Identify the one bot-owned checkpoint status comment."""
    return (
        author_login == "github-actions[bot]"
        and STATUS_COMMENT_MARKER in body
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
        description="Validate optional learner checkpoint issues."
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

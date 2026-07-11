"""Compatibility facade for the original Week 1 notebook API.

New checkpoints should use :mod:`search_agent_lab.checkpoints` directly.
"""

from __future__ import annotations

from .checkpoints.catalog import WEEK_01
from .checkpoints.core import (
    CHECKPOINT_SECTION,
    CODENAME_SECTION,
    HONOR_CONFIRMATION,
    HONOR_SECTION,
    ISSUE_TEMPLATE_FILENAME,
    CodenameParts,
    IssueSubmission,
    ValidationResult,
    build_issue_form_url,
    codename_seed,
    generate_codename,
    main,
    normalize_github_username,
    parse_codename_phrase,
    parse_issue_sections,
)
from .checkpoints.core import parse_issue_submission as _parse_submission
from .checkpoints.core import validate_issue_submission as _validate_submission
from .checkpoints.words import (
    ANIMALS_V1,
    COLOR_BADGES_V1,
    TITLES_V1,
)


CODENAME_VERSION = WEEK_01.codename_version
CHECKPOINT_PHRASE = WEEK_01.phrase
ACHIEVEMENT_MESSAGE = WEEK_01.achievement_message
ISSUE_TITLE_PREFIX = "[Week 1 checkpoint]"
DEFAULT_REPOSITORY = "absurdwall/search-agent-lab"

# Legacy constants remain importable for existing tests and notebook users.
BASE_LABEL = "week-1-checkpoint"
PASSED_LABEL = "week-1-passed"
NEEDS_FIX_LABEL = "week-1-needs-fix"


def parse_issue_submission(body: str) -> IssueSubmission:
    return _parse_submission(
        body,
        default_checkpoint_id=WEEK_01.checkpoint_id,
    )


def validate_issue_submission(
    username: str,
    body: str,
    *,
    title: str = "",
    labels: tuple[str, ...] = (),
) -> ValidationResult:
    return _validate_submission(
        username,
        body,
        title=title,
        labels=labels,
        default_checkpoint_id=WEEK_01.checkpoint_id,
    )


__all__ = (
    "ACHIEVEMENT_MESSAGE",
    "ANIMALS_V1",
    "BASE_LABEL",
    "CHECKPOINT_PHRASE",
    "CHECKPOINT_SECTION",
    "CODENAME_SECTION",
    "CODENAME_VERSION",
    "COLOR_BADGES_V1",
    "DEFAULT_REPOSITORY",
    "HONOR_CONFIRMATION",
    "HONOR_SECTION",
    "ISSUE_TEMPLATE_FILENAME",
    "ISSUE_TITLE_PREFIX",
    "NEEDS_FIX_LABEL",
    "PASSED_LABEL",
    "TITLES_V1",
    "CodenameParts",
    "IssueSubmission",
    "ValidationResult",
    "build_issue_form_url",
    "codename_seed",
    "generate_codename",
    "main",
    "normalize_github_username",
    "parse_codename_phrase",
    "parse_issue_sections",
    "parse_issue_submission",
    "validate_issue_submission",
)


if __name__ == "__main__":
    raise SystemExit(main())

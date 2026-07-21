"""Deterministic assessment for the Week 2 learner checkpoint."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from .checkpoints import WEEK_02, expected_evidence


@dataclass(frozen=True)
class AnswerAssessment:
    """Local assessment for the two learner-supplied checkpoint answers."""

    finish_reason_passed: bool
    component_matches_passed: bool
    hints: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return self.finish_reason_passed and self.component_matches_passed


def _normalize_finish_reason(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).strip().upper()
    return re.sub(r"[^A-Z0-9]+", "_", normalized).strip("_")


def _normalize_component_matches(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value)).strip().upper()
    return re.sub(r"\s+", "", normalized)


def assess_week2_checkpoint_answers(
    finish_reason: object,
    component_matches: object,
) -> AnswerAssessment:
    """Assess checkpoint fields without exposing solutions in the Notebook."""
    evidence = expected_evidence(WEEK_02)
    expected_finish_reason = evidence["finish_reason"]
    expected_matches = "".join(
        evidence[f"component_match_{position}"] for position in range(1, 5)
    )
    finish_reason_passed = (
        _normalize_finish_reason(finish_reason) == expected_finish_reason
    )
    component_matches_passed = (
        _normalize_component_matches(component_matches) == expected_matches
    )

    hints: list[str] = []
    if not finish_reason_passed:
        hints.append(
            "Field 1: open the missing-capability session, select the model event, "
            "and inspect Response metadata rather than the HTTP status."
        )
    if not component_matches_passed:
        hints.append(
            "Field 2: for each observation, identify which component directly "
            "produced, instructed, blocked, or exposed it; enter four letters "
            "in order."
        )
    return AnswerAssessment(
        finish_reason_passed=finish_reason_passed,
        component_matches_passed=component_matches_passed,
        hints=tuple(hints),
    )

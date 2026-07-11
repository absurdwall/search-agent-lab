"""Data-only catalog of optional learner checkpoints."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CheckpointDefinition:
    checkpoint_id: str
    phrase: str
    achievement_message: str
    codename_version: str
    issue_title: str
    expected_evidence: tuple[tuple[str, str], ...]
    checkpoint_label: str | None = None


class UnknownCheckpointError(ValueError):
    """Raised when an issue names a checkpoint outside the public catalog."""


# The ID and expected evidence are part of the locked v1 seed. Future changes
# that should alter public mappings require a new codename version.
WEEK_01 = CheckpointDefinition(
    checkpoint_id="week-01:first-tool-found",
    phrase="Week 1 — First tool found",
    achievement_message="🎉 The agent found its first tool!",
    codename_version="v1",
    issue_title="[Week 1 checkpoint] First tool found",
    expected_evidence=(
        ("tool", "lookup_lab_status"),
        ("status", "ready"),
        ("topic", "google-adk"),
        ("summary", "The deterministic local tool completed."),
    ),
    checkpoint_label="week-01",
)

DEFAULT_CHECKPOINT_ID = WEEK_01.checkpoint_id

CHECKPOINTS: dict[str, CheckpointDefinition] = {
    WEEK_01.checkpoint_id: WEEK_01,
}


def get_checkpoint(checkpoint_id: str) -> CheckpointDefinition:
    """Return one catalog definition or raise a stable public error."""
    try:
        return CHECKPOINTS[checkpoint_id]
    except KeyError as error:
        raise UnknownCheckpointError("Unknown checkpoint ID.") from error


def resolve_checkpoint(
    checkpoint: str | CheckpointDefinition,
) -> CheckpointDefinition:
    if isinstance(checkpoint, CheckpointDefinition):
        return checkpoint
    return get_checkpoint(checkpoint)

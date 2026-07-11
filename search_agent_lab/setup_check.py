"""Pure helpers for gating the learner notebook's real live checkpoint."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .checkpoints import (
    DEFAULT_CHECKPOINT_ID,
    CheckpointDefinition,
    EvidenceValidationError,
    canonicalize_evidence,
    expected_evidence,
    get_checkpoint,
)


TimelineRow = tuple[str, object]


@dataclass(frozen=True)
class LiveCheckpointAssessment:
    succeeded: bool
    evidence: dict[str, str] | None
    message: str


def assess_live_checkpoint(
    rows: Sequence[TimelineRow],
    checkpoint: str | CheckpointDefinition = DEFAULT_CHECKPOINT_ID,
) -> LiveCheckpointAssessment:
    """Validate safe timeline rows produced only from a real ADK run."""
    definition = (
        get_checkpoint(checkpoint)
        if isinstance(checkpoint, str)
        else checkpoint
    )
    expected = expected_evidence(definition)
    expected_tool = expected.get("tool")
    expected_topic = expected.get("topic")

    call_index: int | None = None
    for index, (stage, value) in enumerate(rows):
        if stage != "tool call" or not isinstance(value, Mapping):
            continue
        arguments = value.get("arguments")
        if (
            value.get("tool") == expected_tool
            and isinstance(arguments, Mapping)
            and arguments.get("topic") == expected_topic
        ):
            call_index = index
            break
    if call_index is None:
        return LiveCheckpointAssessment(
            succeeded=False,
            evidence=None,
            message=(
                "Checkpoint not generated: the expected tool call was not "
                "observed."
            ),
        )

    result_index: int | None = None
    observed_evidence: dict[str, object] | None = None
    for index, (stage, value) in enumerate(
        rows[call_index + 1 :],
        call_index + 1,
    ):
        if stage != "tool result" or not isinstance(value, Mapping):
            continue
        result = value.get("result")
        if value.get("tool") != expected_tool or not isinstance(result, Mapping):
            continue
        result_index = index
        observed_evidence = {
            "tool": value.get("tool"),
            "status": result.get("status"),
            "topic": result.get("topic"),
            "summary": result.get("summary"),
        }
        break
    if result_index is None or observed_evidence is None:
        return LiveCheckpointAssessment(
            succeeded=False,
            evidence=None,
            message=(
                "Checkpoint not generated: the expected tool result was not "
                "observed."
            ),
        )

    try:
        canonicalize_evidence(observed_evidence, definition)
    except EvidenceValidationError:
        return LiveCheckpointAssessment(
            succeeded=False,
            evidence=None,
            message=(
                "Checkpoint not generated: the allowlisted tool evidence was "
                "incomplete or changed."
            ),
        )

    validated_evidence = {
        field: value
        for field, value in observed_evidence.items()
        if isinstance(value, str)
    }

    final_seen = any(
        stage == "final answer"
        for stage, _ in rows[result_index + 1 :]
    )
    if not final_seen:
        return LiveCheckpointAssessment(
            succeeded=False,
            evidence=None,
            message=(
                "Checkpoint not generated: a non-thought final answer was "
                "not observed."
            ),
        )

    return LiveCheckpointAssessment(
        succeeded=True,
        evidence=validated_evidence,
        message="Checkpoint evidence validated.",
    )

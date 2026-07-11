from __future__ import annotations

import unittest

from search_agent_lab.checkpoints import WEEK_01, expected_evidence
from search_agent_lab.checks.setup import assess_live_checkpoint


def successful_timeline() -> list[tuple[str, object]]:
    evidence = expected_evidence(WEEK_01)
    return [
        (
            "user input",
            "Use lookup_lab_status for the public topic google-adk.",
        ),
        ("agent", "setup_agent"),
        (
            "tool call",
            {
                "tool": evidence["tool"],
                "arguments": {"topic": evidence["topic"]},
            },
        ),
        (
            "tool result",
            {
                "tool": evidence["tool"],
                "result": {
                    "status": evidence["status"],
                    "topic": evidence["topic"],
                    "summary": evidence["summary"],
                },
            },
        ),
        (
            "final answer",
            "Final response received (content omitted by setup check).",
        ),
    ]


class LiveCheckpointAssessmentTests(unittest.TestCase):
    def test_complete_live_timeline_is_accepted(self) -> None:
        result = assess_live_checkpoint(successful_timeline(), WEEK_01)
        self.assertTrue(result.succeeded)
        self.assertEqual(result.evidence, expected_evidence(WEEK_01))

    def test_missing_tool_call_is_rejected(self) -> None:
        timeline = successful_timeline()
        timeline.pop(2)
        result = assess_live_checkpoint(timeline, WEEK_01)
        self.assertFalse(result.succeeded)
        self.assertIsNone(result.evidence)

    def test_changed_tool_evidence_is_rejected(self) -> None:
        timeline = successful_timeline()
        tool_result = timeline[3][1]
        assert isinstance(tool_result, dict)
        result_value = tool_result["result"]
        assert isinstance(result_value, dict)
        result_value["status"] = "redacted"
        result = assess_live_checkpoint(timeline, WEEK_01)
        self.assertFalse(result.succeeded)
        self.assertIsNone(result.evidence)

    def test_missing_final_answer_is_rejected(self) -> None:
        result = assess_live_checkpoint(successful_timeline()[:-1], WEEK_01)
        self.assertFalse(result.succeeded)
        self.assertIsNone(result.evidence)


if __name__ == "__main__":
    unittest.main()

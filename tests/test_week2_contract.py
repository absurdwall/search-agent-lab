from __future__ import annotations

import unittest

from search_agent_lab.week2_contract import assess_week2_checkpoint_answers


class Week2ContractTests(unittest.TestCase):
    def test_checkpoint_answers_accept_normalized_correct_values(self) -> None:
        assessment = assess_week2_checkpoint_answers(
            " malformed function call ",
            " l i c t ",
        )
        self.assertTrue(assessment.passed)
        self.assertEqual(assessment.hints, ())

    def test_checkpoint_answers_reject_the_notebook_example(self) -> None:
        assessment = assess_week2_checkpoint_answers("stop", "TLIC")
        self.assertFalse(assessment.passed)
        self.assertFalse(assessment.finish_reason_passed)
        self.assertFalse(assessment.component_matches_passed)
        self.assertEqual(len(assessment.hints), 2)


if __name__ == "__main__":
    unittest.main()

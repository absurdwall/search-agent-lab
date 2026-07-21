from __future__ import annotations

import ast
import json
from pathlib import Path
import unittest

import nbformat


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
NOTEBOOK_PATH = REPOSITORY_ROOT / "notebooks/01_glossary_qa.ipynb"
README_PATH = REPOSITORY_ROOT / "README.md"
EVAL_SET_PATH = (
    REPOSITORY_ROOT
    / "week2_repaired_week_lookup/week1_coverage.evalset.json"
)
GLOSSARY_PATH = REPOSITORY_ROOT / "spooky/data/glossary.snapshot.json"


class Week2NotebookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.notebook = nbformat.read(NOTEBOOK_PATH, as_version=4)
        cls.source = "\n".join(cell.source for cell in cls.notebook.cells)
        cls.markdown = "\n".join(
            cell.source
            for cell in cls.notebook.cells
            if cell.cell_type == "markdown"
        )
        cls.readme = README_PATH.read_text(encoding="utf-8")
        cls.cells_by_id = {
            cell.get("id"): cell.source for cell in cls.notebook.cells
        }

    def test_title_and_sections_are_in_order(self) -> None:
        self.assertTrue(
            self.notebook.cells[0].source.startswith(
                "# Week 2 — Build and Debug an Agent Tool"
            )
        )
        headings = [
            line
            for cell in self.notebook.cells
            if cell.cell_type == "markdown"
            for line in cell.source.splitlines()
            if line.startswith("## ")
        ]
        self.assertEqual(
            headings,
            [
                "## 1. Setup",
                "## 2. Compare three Agent configurations",
                "## 3. Assignment — improve a vague tool",
                "## 4. Summary and cleanup",
            ],
        )

    def test_notebook_is_output_free_ast_valid_and_has_unique_ids(self) -> None:
        nbformat.validate(self.notebook)
        cell_ids = [cell.get("id") for cell in self.notebook.cells]
        self.assertNotIn(None, cell_ids)
        self.assertEqual(len(cell_ids), len(set(cell_ids)))
        for index, cell in enumerate(self.notebook.cells):
            if cell.cell_type != "code":
                continue
            self.assertIsNone(cell.execution_count, index)
            self.assertEqual(cell.outputs, [], index)
            ast.parse(cell.source, filename=f"cell-{index}")

    def test_semantic_app_names_match_the_learner_flow(self) -> None:
        required_fragments = (
            'BASELINE_APP = "week2_baseline_fluent"',
            'MISSING_TOOLS_APP = "week2_instruction_without_tools"',
            'GROUNDED_APP = "week2_grounded_glossary"',
            'VAGUE_APP = "week2_vague_week_lookup"',
            'REPAIRED_WEEK_APP = "week2_repaired_week_lookup"',
        )
        for fragment in required_fragments:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, self.source)

    def test_same_question_drives_all_three_comparison_runs(self) -> None:
        baseline = self.cells_by_id["baseline-run"]
        missing = self.cells_by_id["missing-capability-run"]
        grounded = self.cells_by_id["grounded-run"]
        definition = self.cells_by_id["missing-capability-definition"]

        self.assertIn("run_agent(BASELINE_APP, COMPARISON_QUESTION)", baseline)
        self.assertIn("run_agent(MISSING_TOOLS_APP, COMPARISON_QUESTION)", missing)
        self.assertIn("COMPARISON_QUESTION", grounded)
        self.assertNotIn("instruction=", baseline)
        self.assertNotIn("tools=", baseline)
        self.assertIn("instruction=GLOSSARY_INSTRUCTION", definition)
        self.assertIn("tools=[]", definition)
        self.assertIn("instruction=GLOSSARY_INSTRUCTION", grounded)
        self.assertIn("tools=[search_glossary, get_glossary_terms]", grounded)

    def test_required_learner_flow_is_complete_and_in_order(self) -> None:
        required_ids = (
            "setup-code",
            "runtime-start",
            "baseline-run",
            "glossary-load",
            "missing-capability-definition",
            "missing-capability-run",
            "grounded-run",
            "compare-in-adk-web",
            "guardrail-explanation",
            "guardrail-definition",
            "vague-declaration",
            "declaration-json",
            "repair-target",
            "learner-repair-cell",
            "contract-checker",
            "repaired-run",
            "repaired-observe",
            "checkpoint-heading",
            "checkpoint-inputs",
            "checkpoint-validate",
            "repaired-eval",
            "inspect-eval-contract",
            "run-repaired-eval",
            "cleanup-heading",
            "cleanup-code",
        )
        cell_ids = [cell.get("id") for cell in self.notebook.cells]
        positions = [cell_ids.index(cell_id) for cell_id in required_ids]
        self.assertEqual(positions, sorted(positions))

    def test_notebook_defines_the_teaching_tools_and_instruction(self) -> None:
        glossary_source = self.cells_by_id["glossary-load"]
        self.assertIn("def search_glossary(", glossary_source)
        self.assertIn("def get_glossary_terms(", glossary_source)
        self.assertIn("GLOSSARY_INSTRUCTION =", glossary_source)
        self.assertNotIn("from spooky import root_agent", self.source)
        self.assertNotIn("from spooky.agent import", self.source)

    def test_vague_and_repaired_runs_share_instruction_body_and_guardrails(self) -> None:
        vague = self.cells_by_id["vague-declaration"]
        repaired = self.cells_by_id["repaired-run"]
        guardrails = self.cells_by_id["guardrail-definition"]
        for source in (vague, repaired):
            self.assertIn("instruction=WEEK_COVERAGE_INSTRUCTION", source)
            self.assertIn("tools=[find_terms_by_week]", source)
            self.assertIn("before_model_callback=stop_runaway_model_loop", source)
            self.assertIn("before_tool_callback=limit_week_tool_calls", source)
        self.assertIn("MAX_MODEL_CALLS_PER_TURN = 3", guardrails)
        self.assertIn("MAX_WEEK_TOOL_CALLS_PER_TURN = 1", guardrails)

    def test_submission_follows_repaired_run_and_keeps_all_gates(self) -> None:
        cell_ids = [cell.get("id") for cell in self.notebook.cells]
        self.assertLess(cell_ids.index("contract-checker"), cell_ids.index("repaired-run"))
        self.assertLess(cell_ids.index("repaired-run"), cell_ids.index("checkpoint-heading"))
        self.assertLess(cell_ids.index("checkpoint-inputs"), cell_ids.index("checkpoint-validate"))

        checkpoint = self.cells_by_id["checkpoint-validate"]
        self.assertIn(
            'contract_report["passed"] and answer_assessment.passed and repaired_week_run is not None',
            checkpoint,
        )
        inputs = self.cells_by_id["checkpoint-inputs"]
        self.assertIn("FINISH_REASON_ANSWER", inputs)
        self.assertIn("COMPONENT_MATCHES", inputs)
        self.assertIn("GITHUB_USERNAME", inputs)

    def test_optional_eval_is_after_checkpoint_and_before_cleanup(self) -> None:
        cell_ids = [cell.get("id") for cell in self.notebook.cells]
        self.assertLess(cell_ids.index("checkpoint-validate"), cell_ids.index("repaired-eval"))
        self.assertLess(cell_ids.index("repaired-eval"), cell_ids.index("cleanup-heading"))
        self.assertIn("optional", self.cells_by_id["repaired-eval"].casefold())
        self.assertIn("week1_coverage.evalset.json", self.source)

    def test_optional_eval_matches_the_current_week_lookup_contract(self) -> None:
        eval_set = json.loads(EVAL_SET_PATH.read_text(encoding="utf-8"))
        case = eval_set["eval_cases"][0]
        invocation = case["conversation"][0]
        tool_use = invocation["intermediateData"]["toolUses"][0]
        self.assertEqual(case["evalId"], "week1_concepts")
        self.assertEqual(tool_use["name"], "find_terms_by_week")
        self.assertEqual(tool_use["args"], {"introduced_in": "week-01"})

        glossary = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
        week_one_ids = {
            term["id"]
            for term in glossary["terms"]
            if term.get("introduced_in") == "week-01"
        }
        reference = invocation["finalResponse"]["parts"][0]["text"]
        self.assertEqual(len(week_one_ids), 7)
        for term_id in week_one_ids:
            with self.subTest(term_id=term_id):
                self.assertIn(f"#{term_id}", reference)

    def test_runtime_plumbing_is_extracted_from_notebook(self) -> None:
        self.assertIn("Week2NotebookRuntime", self.source)
        for implementation_detail in (
            "get_fast_api_app",
            "BaseAgentLoader",
            "uvicorn",
            "socket",
            "urllib",
        ):
            with self.subTest(implementation_detail=implementation_detail):
                self.assertNotIn(implementation_detail, self.source)

    def test_old_relation_assignment_has_no_dead_references(self) -> None:
        for removed_name in (
            "find_related_terms",
            "some_function",
            "RELATION_TYPES",
            "repaired_relation_run",
            "SCHEMA_CHOICES",
        ):
            with self.subTest(removed_name=removed_name):
                self.assertNotIn(removed_name, self.source)

    def test_checkpoint_solutions_are_not_literal_in_notebook(self) -> None:
        self.assertNotIn("MALFORMED_FUNCTION_CALL", self.source)
        self.assertNotIn("LICT", self.source)
        self.assertIn('COMPONENT_MATCHES = "TLIC"', self.source)
        self.assertIn("assess_week2_checkpoint_answers(", self.source)

    def test_readme_matches_the_current_week2_flow(self) -> None:
        self.assertIn("Agent without tools", self.readme)
        self.assertIn("glossary instruction with its tools registered", self.readme)
        self.assertIn("inspect the generated tool definition", self.readme)
        self.assertIn("repair the Python function interface", self.readme)
        self.assertIn("search_agent_lab/week2_runtime.py", self.readme)
        self.assertNotIn("Start that server manually", self.readme)


if __name__ == "__main__":
    unittest.main()

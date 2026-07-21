from __future__ import annotations

import hashlib
import json
import unittest

from spooky.tools import (
    CANONICAL_GLOSSARY_URL,
    EXPECTED_IDS,
    SCHEMA_VERSION,
    SNAPSHOT_PATH,
    SNAPSHOT_SHA256,
    get_glossary_terms,
    search_glossary,
)


class GlossarySnapshotTests(unittest.TestCase):
    def test_raw_snapshot_checksum(self) -> None:
        self.assertEqual(
            hashlib.sha256(SNAPSHOT_PATH.read_bytes()).hexdigest(),
            SNAPSHOT_SHA256,
        )

    def test_schema_and_expected_ids(self) -> None:
        payload = json.loads(SNAPSHOT_PATH.read_bytes())
        self.assertEqual(payload["schema_version"], SCHEMA_VERSION)
        self.assertEqual(
            tuple(term["id"] for term in payload["terms"]), EXPECTED_IDS
        )
        self.assertEqual(len(payload["terms"]), 16)


class GlossarySearchTests(unittest.TestCase):
    def test_exact_term_match_is_first(self) -> None:
        result = search_glossary("Tool")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["results"][0]["id"], "tool")
        self.assertEqual(result["results"][0]["match"]["kind"], "exact")

    def test_alias_match(self) -> None:
        result = search_glossary("SKILL.md")
        self.assertEqual(result["results"][0]["id"], "skill")
        self.assertIn("aliases", result["results"][0]["match"]["fields"])

    def test_tool_and_skill_question_finds_both(self) -> None:
        result = search_glossary(
            "What is the difference between a Tool and a Skill?"
        )
        ids = [item["id"] for item in result["results"]]
        self.assertEqual(ids[:2], ["tool", "skill"])

    def test_week2_comparison_question_finds_tool_and_sub_agent(self) -> None:
        result = search_glossary(
            "What is the difference between a Tool and a Sub-agent?"
        )
        ids = [item["id"] for item in result["results"]]
        self.assertEqual(ids[:2], ["tool", "sub-agent"])

    def test_react_llm_agent_and_tool_question_finds_all(self) -> None:
        result = search_glossary(
            "How do a ReAct loop, an LLM Agent, and Tools work together?"
        )
        ids = {item["id"] for item in result["results"]}
        self.assertTrue({"react", "llm-agent", "tool"}.issubset(ids))

    def test_order_is_deterministic_and_limited(self) -> None:
        query = "agent model tool session runner callback"
        first = search_glossary(query)
        second = search_glossary(query)
        self.assertEqual(first, second)
        self.assertLessEqual(len(first["results"]), 5)

    def test_no_match_is_structured(self) -> None:
        self.assertEqual(
            search_glossary("What is a vector database?"),
            {
                "status": "not_found",
                "query": "What is a vector database?",
                "results": [],
            },
        )


class GlossaryRetrievalTests(unittest.TestCase):
    def test_duplicate_ids_are_removed_in_requested_order(self) -> None:
        result = get_glossary_terms(["tool", "skill", "tool"])
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            [term["id"] for term in result["terms"]], ["tool", "skill"]
        )

    def test_missing_ids_are_explicit(self) -> None:
        result = get_glossary_terms(["tool", "vector-database"])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["missing_ids"], ["vector-database"])
        self.assertEqual(
            get_glossary_terms(["vector-database"])["status"], "not_found"
        )

    def test_records_are_complete_and_have_canonical_urls(self) -> None:
        result = get_glossary_terms(["tool", "skill"])
        for term in result["terms"]:
            self.assertIn("sections", term)
            self.assertIn("relations", term)
            self.assertEqual(
                term["canonical_url"],
                f"{CANONICAL_GLOSSARY_URL}#{term['id']}",
            )


if __name__ == "__main__":
    unittest.main()

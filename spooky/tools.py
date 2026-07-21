"""Deterministic tools backed only by the committed study-group glossary."""

from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import unicodedata


SNAPSHOT_PATH = Path(__file__).with_name("data") / "glossary.snapshot.json"
SNAPSHOT_SHA256 = "c08049090cb97c8df7196a511c7872f996a5e7d66f72483b8da4e08a109add95"
SCHEMA_VERSION = 1
CANONICAL_GLOSSARY_URL = (
    "https://absurdwall.github.io/search-agent-study-group/glossary/"
)
EXPECTED_IDS = (
    "agent",
    "callback",
    "context-window",
    "google-adk",
    "guardrail",
    "large-language-model",
    "llm-agent",
    "model-context-protocol",
    "prompt",
    "react",
    "runner",
    "session",
    "skill",
    "sub-agent",
    "system-prompt",
    "tool",
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = {
    "a", "an", "and", "are", "between", "do", "does", "how", "in",
    "is", "of", "the", "to", "what", "with", "work",
}


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _tokens(value: str) -> list[str]:
    tokens = _TOKEN_RE.findall(_normalize(value).replace("-", " "))
    return [token[:-1] if len(token) > 3 and token.endswith("s") else token for token in tokens]


@lru_cache(maxsize=1)
def _load_snapshot() -> tuple[dict[str, object], ...]:
    raw_bytes = SNAPSHOT_PATH.read_bytes()
    if hashlib.sha256(raw_bytes).hexdigest() != SNAPSHOT_SHA256:
        raise ValueError("The committed glossary snapshot checksum is invalid.")

    payload = json.loads(raw_bytes)
    terms = payload.get("terms") if isinstance(payload, dict) else None
    if payload.get("schema_version") != SCHEMA_VERSION or not isinstance(terms, list):
        raise ValueError("The committed glossary snapshot schema is invalid.")
    ids = tuple(term.get("id") for term in terms if isinstance(term, dict))
    if ids != EXPECTED_IDS:
        raise ValueError("The committed glossary snapshot term IDs are invalid.")
    return tuple(terms)


def _search_fields(term: dict[str, object]) -> dict[str, list[str]]:
    aliases = term.get("aliases")
    sections = term.get("sections")
    return {
        "id": [str(term["id"])],
        "term": [str(term["term"])],
        "aliases": [str(value) for value in aliases] if isinstance(aliases, list) else [],
        "Simple definition": [str(sections.get("Simple definition", ""))]
        if isinstance(sections, dict)
        else [],
        "Working definition": [str(sections.get("Working definition", ""))]
        if isinstance(sections, dict)
        else [],
    }


def _match_term(
    term: dict[str, object], query: str, query_tokens: list[str]
) -> tuple[tuple[int, int, int], dict[str, object]] | None:
    fields = _search_fields(term)
    query_normalized = _normalize(query)
    query_set = set(query_tokens)
    name_values = fields["id"] + fields["term"] + fields["aliases"]

    if any(query_normalized == _normalize(value) for value in name_values):
        matched_fields = [
            field
            for field in ("id", "term", "aliases")
            if any(query_normalized == _normalize(value) for value in fields[field])
        ]
        return (3, len(query_tokens), 0), {"kind": "exact", "fields": matched_fields}

    name_matches: list[tuple[int, str]] = []
    for field in ("id", "term", "aliases"):
        for value in fields[field]:
            value_tokens = _tokens(value)
            if value_tokens and set(value_tokens).issubset(query_set):
                positions = [query_tokens.index(token) for token in value_tokens]
                name_matches.append((min(positions), field))
    if name_matches:
        position = min(position for position, _ in name_matches)
        matched_fields = list(dict.fromkeys(field for _, field in name_matches))
        coverage = max(len(_tokens(value)) for value in name_values if set(_tokens(value)).issubset(query_set))
        return (2, coverage, -position), {"kind": "name", "fields": matched_fields}

    matched_fields: list[str] = []
    matched_tokens: set[str] = set()
    for field, values in fields.items():
        field_tokens = {token for value in values for token in _tokens(value)}
        overlap = query_set & field_tokens
        if overlap:
            matched_fields.append(field)
            matched_tokens.update(overlap)
    if not matched_tokens:
        return None
    first_position = min(query_tokens.index(token) for token in matched_tokens)
    return (1, len(matched_tokens), -first_position), {
        "kind": "content",
        "fields": matched_fields,
    }


def search_glossary(query: str) -> dict[str, object]:
    """Search study-group glossary names and definitions for up to five candidates."""
    if not isinstance(query, str):
        return {"status": "not_found", "query": "", "results": []}
    query_tokens = [token for token in _tokens(query) if token not in _STOP_WORDS]
    if not query_tokens:
        return {"status": "not_found", "query": query, "results": []}

    ranked: list[tuple[tuple[int, int, int], int, dict[str, object], dict[str, object]]] = []
    for index, term in enumerate(_load_snapshot()):
        match = _match_term(term, query, query_tokens)
        if match is not None:
            score, match_info = match
            ranked.append((score, index, term, match_info))
    ranked.sort(key=lambda item: (-item[0][0], -item[0][1], -item[0][2], item[1]))

    results = [
        {
            "id": term["id"],
            "term": term["term"],
            "simple_definition": term["sections"]["Simple definition"],
            "match": match_info,
        }
        for _, _, term, match_info in ranked[:5]
    ]
    return {
        "status": "ok" if results else "not_found",
        "query": query,
        "results": results,
    }


def get_glossary_terms(term_ids: list[str]) -> dict[str, object]:
    """Return complete local glossary records for requested canonical IDs."""
    if not isinstance(term_ids, list):
        term_ids = []
    requested: list[str] = []
    for value in term_ids:
        normalized = _normalize(value) if isinstance(value, str) else ""
        if normalized and normalized not in requested:
            requested.append(normalized)

    by_id = {str(term["id"]): term for term in _load_snapshot()}
    found: list[dict[str, object]] = []
    missing: list[str] = []
    for term_id in requested:
        if term_id not in by_id:
            missing.append(term_id)
            continue
        record = deepcopy(by_id[term_id])
        record["canonical_url"] = f"{CANONICAL_GLOSSARY_URL}#{term_id}"
        found.append(record)

    status = "partial" if found and missing else "ok" if found else "not_found"
    return {"status": status, "terms": found, "missing_ids": missing}

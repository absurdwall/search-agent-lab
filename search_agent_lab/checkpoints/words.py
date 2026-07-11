"""Versioned codename word lists shared by every checkpoint."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WordLists:
    color_badges: tuple[tuple[str, str], ...]
    animals: tuple[str, ...]
    titles: tuple[str, ...]


# Do not reorder or edit v1. Existing Week 1 codenames depend on these exact
# positions. Introduce a new version for future vocabulary changes.
COLOR_BADGES_V1: tuple[tuple[str, str], ...] = (
    ("🔴", "Crimson"),
    ("🟠", "Amber"),
    ("🟡", "Golden"),
    ("🟢", "Emerald"),
    ("🔵", "Azure"),
    ("🟣", "Violet"),
    ("🩷", "Coral"),
    ("⚪", "Silver"),
)

ANIMALS_V1: tuple[str, ...] = (
    "Badger",
    "Dolphin",
    "Falcon",
    "Fox",
    "Gecko",
    "Hare",
    "Lynx",
    "Otter",
    "Owl",
    "Panda",
    "Raven",
    "Tiger",
)

TITLES_V1: tuple[str, ...] = (
    "Builder",
    "Cartographer",
    "Catalyst",
    "Explorer",
    "Investigator",
    "Navigator",
    "Pathfinder",
    "Scout",
    "Tinkerer",
    "Toolsmith",
    "Trailblazer",
    "Wayfinder",
)

WORD_LISTS: dict[str, WordLists] = {
    "v1": WordLists(
        color_badges=COLOR_BADGES_V1,
        animals=ANIMALS_V1,
        titles=TITLES_V1,
    ),
}

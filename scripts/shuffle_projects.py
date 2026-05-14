# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Aayush Sinha
"""
shuffle_projects.py - Randomly reorder project list entries in README.md.

Scans README.md for contiguous blocks of Markdown list items (lines that
start with "- ") and shuffles only blocks where every item contains a
GitHub URL. This ensures non-project lists (domains, links, etc.) are
left untouched. Writes the file back only when the order actually changed.

Usage
-----
    python scripts/shuffle_projects.py

No environment variables or external dependencies are required.
"""

import os
import random
import re

README_PATH = os.path.join(os.path.dirname(__file__), "..", "README.md")

# Same pattern used by update_stars.py - identifies lines that reference a
# GitHub repository. Only list blocks containing these lines are shuffled.
GITHUB_URL_RE = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")


def is_github_project_block(segment: list[str]) -> bool:
    """Return True if every item in the list segment links to a GitHub repo.

    A block qualifies for shuffling only when all of its lines contain a
    GitHub URL, so non-project lists (domains, plain links, etc.) are never
    reordered.
    """
    return bool(segment) and all(GITHUB_URL_RE.search(line) for line in segment)


def split_into_segments(lines: list[str]) -> list[list[str]]:
    """Split the file lines into alternating non-list and list segments.

    Each segment is a list of consecutive lines that are either all list
    items (starting with "- ") or all non-list lines. Preserves the
    original order so segments can be reassembled after shuffling.

    Returns a list of segments where each segment is itself a list of
    line strings (with their original newline characters).
    """
    segments: list[list[str]] = []
    current: list[str] = []
    in_list = False

    for line in lines:
        is_list_item = line.startswith("- ")
        if is_list_item != in_list:
            if current:
                segments.append(current)
            current = [line]
            in_list = is_list_item
        else:
            current.append(line)

    if current:
        segments.append(current)

    return segments


def shuffle_until_different(items: list[str]) -> list[str]:
    """Return a shuffled copy of items that differs from the original.

    Retries up to 100 times to guarantee a different ordering when the
    list has more than one unique permutation. Falls back to the last
    shuffle result if all attempts produced the same order (e.g. a
    single-item list).
    """
    if len(items) <= 1:
        return list(items)

    original = list(items)
    result = list(items)

    for _ in range(100):
        random.shuffle(result)
        if result != original:
            return result

    return result


def main() -> None:
    """Read README.md, shuffle each GitHub project list block, and write it back.

    List blocks that do not contain GitHub URLs (e.g. domain lists) are left
    in their original order. Exits without modifying the file if no
    qualifying blocks are found or every block shuffles into the same order.
    """
    with open(README_PATH, encoding="utf-8") as fh:
        original = fh.read()

    lines = original.splitlines(keepends=True)
    segments = split_into_segments(lines)

    changed = False
    new_segments: list[list[str]] = []

    for segment in segments:
        if segment[0].startswith("- ") and is_github_project_block(segment):
            shuffled = shuffle_until_different(segment)
            if shuffled != segment:
                changed = True
            new_segments.append(shuffled)
        else:
            new_segments.append(segment)

    if changed:
        new_content = "".join(line for seg in new_segments for line in seg)
        with open(README_PATH, "w", encoding="utf-8") as fh:
            fh.write(new_content)
        print("README.md updated with shuffled project order.")
    else:
        print("Project order unchanged — README not modified.")


if __name__ == "__main__":
    main()

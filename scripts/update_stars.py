# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Aayush Sinha
"""
update_stars.py - Refresh GitHub star counts in README.md.

Scans README.md for GitHub repository URLs, fetches the current
stargazer count for each referenced repo via the GitHub REST API,
and rewrites the trailing ``[ X⭐]`` tokens in-place.

Usage
-----
    GITHUB_TOKEN=<token> python scripts/update_stars.py

Environment Variables
---------------------
GITHUB_TOKEN (optional)
    A GitHub personal access token or the ``secrets.GITHUB_TOKEN``
    value injected automatically by GitHub Actions.  Unauthenticated
    requests are allowed but capped at 60/hour; a token raises the
    limit to 5,000/hour. No extra OAuth scopes are required for
    public repositories.

Algorithm
---------
1.  Parse README.md and collect every ``{owner}/{repo}`` slug found
    in GitHub URLs.
2.  For each unique owner, paginate ``GET /users/{owner}/repos``
    (100 per page). Stop early once every required repo for that
    owner has been seen; otherwise stop at the last page naturally.
3.  Any repo still missing after pagination is fetched individually
    via ``GET /repos/{owner}/{repo}`` as a fallback (handles private
    repos and edge cases where the list endpoint omits a repo).
4.  Rewrite only lines whose ``[ X⭐]`` token has changed; leave all
    other content untouched to keep diffs minimal.
"""

import json
import os
import re
import urllib.request
from urllib.error import HTTPError

# Resolved relative to this script's location so it works regardless of the
# working directory from which the script is invoked.
README_PATH = os.path.join(os.path.dirname(__file__), "..", "README.md")

# Captures owner and repo from a full GitHub HTTPS URL.
# Stops at ), whitespace, # and similar delimiters that cannot appear in a
# repo name, preventing false matches inside Markdown link syntax.
GITHUB_URL_RE = re.compile(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")

# Matches the token we write back, e.g. [ 8⭐] or [ 42⭐].
# The leading space before the number is intentional - kept for UI alignment.
STAR_TOKEN_RE = re.compile(r"\[[ \d]*⭐\]")


def make_request(url: str, token: str | None) -> list | dict:
    """Send an authenticated GET request to the GitHub REST API.

    Args:
        url:   Full API endpoint URL.
        token: Bearer token for authentication, or ``None`` for
               unauthenticated access (60 req/hour rate limit applies).

    Returns:
        Parsed JSON response as a ``list`` (collection endpoints) or
        ``dict`` (single-resource endpoints).

    Raises:
        urllib.error.HTTPError: Propagated as-is; callers decide how to
            handle specific status codes (e.g. 404 for missing repos).
    """
    headers = {
        "Accept": "application/vnd.github+json",
        # Pin the API version so behaviour stays stable even when GitHub
        # releases a newer default version.
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def fetch_stars_via_list(
    owner: str,
    needed: set[str],
    token: str | None,
) -> dict[str, int]:
    """Fetch star counts for a set of repos using the owner's repo list API.

    Paginates ``GET /users/{owner}/repos`` in batches of 100 and returns
    early as soon as every name in ``needed`` has been found, avoiding
    unnecessary page fetches for owners with many repositories.

    Args:
        owner:  GitHub username or organisation name.
        needed: Set of repository names (without the owner prefix) whose
                star counts are required.
        token:  Bearer token passed through to :func:`make_request`.

    Returns:
        Mapping of ``{repo_name: stargazers_count}`` for every repo in
        ``needed`` that was found in the list. Repos absent from the
        list are simply omitted; the caller handles them as fallbacks.
    """
    stars: dict[str, int] = {}
    remaining = set(needed)
    page = 1

    while remaining:
        url = f"https://api.github.com/users/{owner}/repos?per_page=100&page={page}"
        try:
            repos = make_request(url, token)
        except HTTPError as exc:
            print(f"  List API error {exc.code} for {owner} page {page}: {exc.reason}")
            break

        if not repos:
            break

        for repo in repos:
            name = repo["name"]
            if name in remaining:
                stars[name] = repo["stargazers_count"]
                remaining.discard(name)

        # A page with fewer than 100 items is the last page; no point
        # requesting page N+1 - it would return an empty list.
        if len(repos) < 100:
            break

        page += 1

    return stars


def fetch_stars_individual(owner: str, repo: str, token: str | None) -> int | None:
    """Fetch the star count for a single repo via its dedicated endpoint.

    This is the fallback path for repos that did not appear in the
    paginated list - e.g. repos returned only to authenticated users,
    or any edge case where the list endpoint omitted an entry.

    Args:
        owner: GitHub username or organisation name.
        repo:  Repository name (without the owner prefix).
        token: Bearer token passed through to :func:`make_request`.

    Returns:
        ``stargazers_count`` integer on success, or ``None`` if the
        request fails (repo deleted, private without sufficient token
        scope, network error, etc.).
    """
    url = f"https://api.github.com/repos/{owner}/{repo}"
    try:
        data = make_request(url, token)
        return data["stargazers_count"]
    except HTTPError as exc:
        print(f"  Individual API error {exc.code} for {owner}/{repo}: {exc.reason}")
        return None


def main() -> None:
    """Orchestrate the full fetch-and-rewrite pipeline.

    Reads README.md, resolves star counts for every linked GitHub repo,
    and writes the file back only when at least one count has changed.
    Exits cleanly with a message when nothing needs updating.
    """
    token = os.environ.get("GITHUB_TOKEN")

    with open(README_PATH, encoding="utf-8") as fh:
        original = fh.read()

    # Group required repos by owner so we can make one list request per
    # owner rather than one per repo.
    needed: dict[str, set[str]] = {}
    for owner, repo in GITHUB_URL_RE.findall(original):
        needed.setdefault(owner, set()).add(repo)

    if not needed:
        print("No GitHub URLs found in README — nothing to do.")
        return

    # star_lookup maps "owner/repo" to stargazers_count
    star_lookup: dict[str, int] = {}

    for owner, repos in needed.items():
        print(f"Fetching repo list for {owner} (need: {repos})")
        found = fetch_stars_via_list(owner, repos, token)
        for repo_name, count in found.items():
            star_lookup[f"{owner}/{repo_name}"] = count

        # Any repos the list endpoint did not return get a direct lookup.
        missing = repos - found.keys()
        for repo_name in missing:
            print(f"  Fallback: fetching {owner}/{repo_name} individually")
            count = fetch_stars_individual(owner, repo_name, token)
            if count is not None:
                star_lookup[f"{owner}/{repo_name}"] = count

    updated_lines = []
    changed = False

    for line in original.splitlines(keepends=True):
        match = GITHUB_URL_RE.search(line)
        if match:
            slug = f"{match.group(1)}/{match.group(2)}"
            if slug in star_lookup:
                new_token = f"[ {star_lookup[slug]}⭐]"
                new_line = STAR_TOKEN_RE.sub(new_token, line)
                if new_line != line:
                    changed = True
                line = new_line
        updated_lines.append(line)

    if changed:
        with open(README_PATH, "w", encoding="utf-8") as fh:
            fh.write("".join(updated_lines))
        print("README.md updated with new star counts.")
    else:
        print("Star counts unchanged — README not modified.")


if __name__ == "__main__":
    main()

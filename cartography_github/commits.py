"""Incremental GitHub commit collection built on Cartography's commit loader."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import neo4j

import cartography.intel.github.commits as upstream
from cartography.client.core.tx import read_list_of_dicts_tx
from cartography.util import timeit

logger = logging.getLogger(__name__)


def _get_repo_pushedat_map(
    neo4j_session: neo4j.Session,
    organization: str,
    repo_names: list[str],
) -> dict[str, Any]:
    if not repo_names:
        return {}
    repo_urls = {
        name: f"https://github.com/{organization}/{name}" for name in repo_names
    }
    rows = neo4j_session.execute_read(
        read_list_of_dicts_tx,
        """
        UNWIND $repo_urls AS url
        MATCH (repo:GitHubRepository {id: url})
        RETURN repo.id AS url, repo.pushedat AS pushedat
        """,
        repo_urls=list(repo_urls.values()),
    )
    by_url = {row["url"]: row["pushedat"] for row in rows}
    return {name: by_url.get(url) for name, url in repo_urls.items()}


def _parse_pushedat(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _filter_stale_repo_names(
    repo_names: list[str],
    pushedat_by_repo: dict[str, Any],
    lookback_date: datetime,
) -> list[str]:
    eligible: list[str] = []
    for repo_name in repo_names:
        pushedat = pushedat_by_repo.get(repo_name)
        pushed_dt = _parse_pushedat(pushedat)
        # Missing or malformed bookmarks are not evidence that a repo is stale.
        if pushed_dt is None or pushed_dt >= lookback_date:
            eligible.append(repo_name)
    return eligible


@timeit
def sync_github_commits(
    neo4j_session: neo4j.Session,
    token: str,
    api_url: str,
    organization: str,
    repo_names: list[str],
    update_tag: int,
    lookback_days: int = 30,
    *,
    skip_stale_repos: bool = False,
) -> None:
    """Fetch commits only for recently pushed repos, then run upstream cleanup."""
    if skip_stale_repos:
        lookback_date = datetime.now(timezone.utc) - timedelta(days=lookback_days)
        pushedat_by_repo = _get_repo_pushedat_map(
            neo4j_session, organization, repo_names
        )
        eligible = _filter_stale_repo_names(
            repo_names, pushedat_by_repo, lookback_date
        )
        logger.info(
            "Skipping commit fetch for %d/%d repos in org %s with no push in the "
            "last %d days.",
            len(repo_names) - len(eligible),
            len(repo_names),
            organization,
            lookback_days,
        )
        repo_names = eligible

    upstream.process_repo_commits_batch(
        neo4j_session,
        token,
        api_url,
        organization,
        repo_names,
        update_tag,
        lookback_days=lookback_days,
        batch_size=10,
    )
    upstream.cleanup_github_commit_relationships(
        neo4j_session, organization, update_tag
    )

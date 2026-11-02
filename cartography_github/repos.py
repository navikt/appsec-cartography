"""Incremental, bounded-concurrency GitHub repository collection."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any
from typing import cast
from urllib.parse import quote

import neo4j
import requests

import cartography.intel.github.repos as upstream
from cartography.client.core.tx import read_list_of_dicts_tx, run_write_query
from cartography.helpers import backoff_handler
from cartography.util import retries_with_backoff, run_analysis_job, timeit

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitHubRepoSyncResult:
    """Compatibility result returned by this stage and consumed by orchestration."""

    repos: list[dict[str, Any]]
    manifests: list[dict[str, Any]]
    manifests_cleanup_safe: bool
    repo_pushedat_updates: list[dict[str, str]] = field(default_factory=list)
    repos_complete: bool = True


def _write_synced_pushedat(
    neo4j_session: neo4j.Session,
    updates: list[dict[str, str]],
) -> None:
    """Persist the common incremental bookmark after all downstream stages finish."""
    if updates:
        run_write_query(
            neo4j_session,
            """
            UNWIND $updates AS u
            MATCH (repo:GitHubRepository {id: u.repo_url})
            SET repo.synced_pushedat = u.pushedat
            """,
            updates=updates,
        )


def _write_repo_pushedat(
    neo4j_session: neo4j.Session,
    updates: list[dict[str, str]],
) -> None:
    """Persist GitHub's current pushedAt value (not present in the 0.143 schema)."""
    if updates:
        run_write_query(
            neo4j_session,
            """
            UNWIND $updates AS u
            MATCH (repo:GitHubRepository {id: u.repo_url})
            SET repo.pushedat = u.pushedat
            """,
            updates=updates,
        )


def _get_manifests_synced_bookmarks(
    neo4j_session: neo4j.Session,
    repo_urls: list[str],
) -> dict[str, str | None]:
    if not repo_urls:
        return {}
    rows = neo4j_session.execute_read(
        read_list_of_dicts_tx,
        """
        UNWIND $repo_urls AS repo_url
        MATCH (repo:GitHubRepository {id: repo_url})
        RETURN repo.id AS url,
               repo.manifests_synced_pushedat AS manifests_synced_pushedat
        """,
        repo_urls=repo_urls,
    )
    return {row["url"]: row["manifests_synced_pushedat"] for row in rows}


def _update_manifests_synced_bookmarks(
    neo4j_session: neo4j.Session,
    updates: list[dict[str, str]],
) -> None:
    """Only mark per-repo manifests current after a complete fetch for that repo."""
    if updates:
        run_write_query(
            neo4j_session,
            """
            UNWIND $updates AS u
            MATCH (repo:GitHubRepository {id: u.repo_url})
            SET repo.manifests_synced_pushedat = u.pushedat
            """,
            updates=updates,
        )


def _touch_skipped_manifests(
    neo4j_session: neo4j.Session,
    repo_urls: list[str],
    update_tag: int,
) -> None:
    """Keep manifests, dependencies, and cleanup-owned edges fresh when skipped."""
    if not repo_urls:
        return
    run_write_query(
        neo4j_session,
        """
        UNWIND $repo_urls AS repo_url
        MATCH (:GitHubRepository {id: repo_url})-[hm:HAS_MANIFEST]->(m:DependencyGraphManifest)
        SET m.lastupdated = $update_tag, hm.lastupdated = $update_tag
        WITH DISTINCT m
        MATCH (:GitHubOrganization)-[res:RESOURCE]->(m)
        SET res.lastupdated = $update_tag
        """,
        repo_urls=repo_urls,
        update_tag=update_tag,
    )
    run_write_query(
        neo4j_session,
        """
        UNWIND $repo_urls AS repo_url
        MATCH (:GitHubRepository {id: repo_url})-[:HAS_MANIFEST]->(:DependencyGraphManifest)
              -[hd:HAS_DEP]->(d:Dependency)
        SET d.lastupdated = $update_tag, hd.lastupdated = $update_tag
        """,
        repo_urls=repo_urls,
        update_tag=update_tag,
    )
    run_write_query(
        neo4j_session,
        """
        UNWIND $repo_urls AS repo_url
        MATCH (:GitHubRepository {id: repo_url})-[req:REQUIRES]->(:Dependency)
        SET req.lastupdated = $update_tag
        """,
        repo_urls=repo_urls,
        update_tag=update_tag,
    )
    run_write_query(
        neo4j_session,
        """
        UNWIND $repo_urls AS repo_url
        MATCH (:GitHubRepository {id: repo_url})-[:HAS_MANIFEST]->(:DependencyGraphManifest)
              -[mc:MATCHES_CODEOWNER_RULE]->(:GitHubCodeOwnerRule)
        SET mc.lastupdated = $update_tag
        """,
        repo_urls=repo_urls,
        update_tag=update_tag,
    )


def _fetch_manifest(
    repo: dict[str, Any],
    token: str,
    api_url: str,
    organization: str,
    skip_unchanged: bool,
) -> tuple[str, list[dict[str, Any]], bool, str | None]:
    repo_url = repo["url"]
    if repo.get("isArchived") or repo.get("isDisabled"):
        return repo_url, [], True, "archived"
    pushedat = repo.get("pushedAt")
    if (
        skip_unchanged
        and pushedat is not None
        and pushedat == repo.get("manifests_synced_pushedat")
    ):
        return repo_url, [], True, "unchanged"
    manifests, cleanup_safe = upstream._get_repo_dep_manifests(
        token, api_url, organization, repo["name"]
    )
    return repo_url, manifests, cleanup_safe, None


def _get_dep_manifests_for_repos(
    repo_data: list[dict[str, Any] | None],
    organization: str,
    api_url: str,
    token: str,
    *,
    neo4j_session: neo4j.Session,
    update_tag: int,
    incremental_sync: bool,
    parallel_workers: int,
) -> tuple[dict[str, dict[str, Any]], bool]:
    repos = [repo for repo in repo_data if repo and repo.get("url") and repo.get("name")]
    bookmarks = _get_manifests_synced_bookmarks(
        neo4j_session, [repo["url"] for repo in repos]
    ) if incremental_sync else {}
    for repo in repos:
        repo["manifests_synced_pushedat"] = bookmarks.get(repo["url"])

    eligible = [
        repo
        for repo in repos
        if not (incremental_sync and (repo.get("isArchived") or repo.get("isDisabled")))
    ]
    logger.info(
        "Fetching dependency manifests for %d/%d repos in %s with %d workers.",
        len(eligible),
        len(repos),
        organization,
        parallel_workers,
    )
    manifests_by_url: dict[str, dict[str, Any]] = {}
    skipped_urls: list[str] = []
    synced_bookmarks: list[dict[str, str]] = []
    cleanup_safe = True
    failures = 0
    with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
        futures = {
            executor.submit(
                _fetch_manifest,
                repo,
                token,
                api_url,
                organization,
                incremental_sync,
            ): repo
            for repo in eligible
        }
        for future in as_completed(futures):
            repo = futures[future]
            try:
                repo_url, manifests, repo_cleanup_safe, skip_reason = future.result()
            except (
                upstream.DependencyGraphForbiddenError,
                requests.exceptions.RequestException,
            ):
                logger.warning(
                    "Failed to fetch dependency manifests for repo %s.",
                    repo.get("name"),
                    exc_info=True,
                )
                cleanup_safe = False
                failures += 1
                continue
            cleanup_safe = cleanup_safe and repo_cleanup_safe
            if manifests:
                manifests_by_url[repo_url] = {"nodes": manifests}
            if skip_reason in ("unchanged", "archived"):
                skipped_urls.append(repo_url)
            elif repo_cleanup_safe and repo.get("pushedAt"):
                synced_bookmarks.append(
                    {"repo_url": repo_url, "pushedat": repo["pushedAt"]}
                )

    _update_manifests_synced_bookmarks(neo4j_session, synced_bookmarks)
    # Archived repositories are intentionally not fetched, but their existing
    # graph data is retained. They are included here so stale-tag cleanup cannot
    # remove records simply because the repository was archived.
    if incremental_sync:
        archived_urls = [
            repo["url"]
            for repo in repos
            if repo.get("isArchived") or repo.get("isDisabled")
        ]
        skipped_urls.extend(archived_urls)
    _touch_skipped_manifests(neo4j_session, list(set(skipped_urls)), update_tag)
    if failures:
        logger.warning(
            "Skipped dependency manifests for %d of %d repos in org %s after errors.",
            failures,
            len(eligible),
            organization,
        )
    return manifests_by_url, cleanup_safe


def _fetch_collaborators_for_repo(
    repo: dict[str, Any],
    affiliation: str,
    organization: str,
    api_url: str,
    token: str,
) -> tuple[str, list[Any]]:
    data = upstream._get_repo_collaborators_for_multiple_repos(
        [repo], affiliation, organization, api_url, token
    )
    return repo["url"], data.get(repo["url"], [])


def _get_collaborators(
    repos: list[dict[str, Any] | None],
    organization: str,
    api_url: str,
    token: str,
    parallel_workers: int,
) -> tuple[dict[str, list[Any]], dict[str, list[Any]]]:
    direct: dict[str, list[Any]] = {}
    outside: dict[str, list[Any]] = {}
    eligible = [repo for repo in repos if repo and repo.get("name") and repo.get("url")]
    with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
        futures = {
            executor.submit(
                _fetch_collaborators_for_repo,
                repo,
                affiliation,
                organization,
                api_url,
                token,
            ): (repo, affiliation)
            for repo in eligible
            for affiliation in ("DIRECT", "OUTSIDE")
        }
        try:
            for future in as_completed(futures):
                repo_url, collaborators = future.result()
                target = direct if futures[future][1] == "DIRECT" else outside
                target[repo_url] = collaborators
        except (TypeError, ValueError):
            logger.warning(
                "Unable to list repo collaborators; continuing without complete collaborator data.",
                exc_info=True,
            )
    return direct, outside


def _get_repo_data_with_pushedat(
    token: str,
    api_url: str,
    organization: str,
) -> list[dict[str, Any] | None]:
    query = upstream.GITHUB_ORG_REPOS_PAGINATED_GRAPHQL
    if "                    pushedAt" not in query:
        if "                    updatedAt\n" not in query:
            raise RuntimeError(
                "Cartography 0.143 GitHub repository query changed; cannot add pushedAt safely."
            )
        query = query.replace(
            "                    updatedAt\n",
            "                    updatedAt\n                    pushedAt\n",
            1,
        )
    connection, _ = upstream.fetch_all(
        token,
        api_url,
        organization,
        query,
        "repositories",
        count=50,
    )
    return cast(list[dict[str, Any] | None], connection.nodes)


def _fetch_rulesets_for_repo(
    repo: dict[str, Any],
    token: str,
    base_url: str,
    owner: str,
    detail_cache: dict[tuple[Any, ...], dict[str, Any]],
    cache_lock: Any,
) -> tuple[str, dict[str, Any]]:
    repo_name = repo["name"]
    repo_url = repo["url"]
    endpoint = f"/repos/{owner}/{quote(repo_name, safe='')}/rulesets"
    summaries = upstream.fetch_all_rest_api_pages(
        token,
        base_url,
        endpoint,
        result_key="rulesets",
        raise_on_status=(403, 404),
        params={"per_page": 100, "includes_parents": "true"},
    )
    normalized = []
    for summary in summaries:
        cache_key = upstream._rest_ruleset_cache_key(summary)
        with cache_lock:
            detail = detail_cache.get(cache_key)
        if detail is None:
            detail = upstream.call_github_rest_api(
                f"{endpoint}/{summary['id']}",
                token,
                base_url,
                params={"includes_parents": "true"},
            )
            with cache_lock:
                detail_cache[cache_key] = detail
        normalized.append(upstream._normalize_rest_ruleset(detail))
    return repo_url, {"nodes": normalized, "totalCount": len(normalized)}


def _get_repo_rulesets_by_url_parallel(
    token: str,
    api_url: str,
    organization: str,
    repos: list[dict[str, Any] | None],
    parallel_workers: int,
) -> dict[str, dict[str, Any]]:
    base_url = upstream.rest_api_base_url(api_url)
    owner = quote(organization, safe="")
    detail_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
    cache_lock = threading.Lock()
    eligible = [repo for repo in repos if repo and repo.get("name") and repo.get("url")]
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
        futures = {
            executor.submit(
                _fetch_rulesets_for_repo,
                repo,
                token,
                base_url,
                owner,
                detail_cache,
                cache_lock,
            ): repo
            for repo in eligible
        }
        for future in as_completed(futures):
            repo_url, repo_rulesets = future.result()
            results[repo_url] = repo_rulesets
    return results


def _get_privileged_details_parallel(
    token: str,
    api_url: str,
    organization: str,
    parallel_workers: int,
) -> dict[str, dict[str, Any]]:
    connection, _ = upstream.fetch_all(
        token,
        api_url,
        organization,
        upstream.GITHUB_ORG_REPOS_PRIVILEGED_PAGINATED_GRAPHQL,
        "repositories",
        count=50,
    )
    privileged_repos = [repo for repo in connection.nodes if repo is not None]
    rulesets = _get_repo_rulesets_by_url_parallel(
        token, api_url, organization, privileged_repos, parallel_workers
    )
    return {
        repo["url"]: {
            "directCollaborators": repo.get("directCollaborators"),
            "outsideCollaborators": repo.get("outsideCollaborators"),
            "branchProtectionRules": repo.get("branchProtectionRules"),
            "rulesets": rulesets.get(repo["url"]),
        }
        for repo in privileged_repos
        if repo.get("url")
    }


@timeit
def sync(
    neo4j_session: neo4j.Session,
    common_job_parameters: dict[str, Any],
    github_api_key: str,
    github_url: str,
    organization: str,
    *,
    parallel_workers: int = 1,
    incremental_sync: bool = False,
) -> GitHubRepoSyncResult:
    """Fetch and load GitHub repository data, with optional incremental manifests."""
    if parallel_workers < 1:
        raise ValueError("parallel_workers must be at least 1")
    logger.info("Syncing GitHub repos")
    repos_json = _get_repo_data_with_pushedat(
        github_api_key, github_url, organization
    )
    repos_complete = all(repo is not None for repo in repos_json)

    privileged_data: dict[str, dict[str, Any]] = {}
    rulesets_cleanup_safe = True
    if upstream._repos_need_privileged_details(repos_json):
        try:
            privileged_data = _get_privileged_details_parallel(
                github_api_key,
                github_url,
                organization,
                parallel_workers,
            )
        except (requests.exceptions.RequestException, ValueError):
            rulesets_cleanup_safe = False
            logger.warning(
                "Could not fetch privileged GitHub repository data for %s; preserving existing rulesets.",
                organization,
                exc_info=True,
            )
    repos_json, _, _ = upstream._merge_repos_with_privileged_details(
        repos_json, privileged_data
    )

    direct, outside = _get_collaborators(
        repos_json, organization, github_url, github_api_key, parallel_workers
    )
    dep_manifests_by_url, manifests_cleanup_safe = _get_dep_manifests_for_repos(
        repos_json,
        organization,
        github_url,
        github_api_key,
        neo4j_session=neo4j_session,
        update_tag=common_job_parameters["UPDATE_TAG"],
        incremental_sync=incremental_sync,
        parallel_workers=parallel_workers,
    )
    for repo in repos_json:
        if repo is not None and repo.get("url") in dep_manifests_by_url:
            repo["dependencyGraphManifests"] = dep_manifests_by_url[repo["url"]]

    security_data = upstream.get_repo_security_and_analysis_by_url(
        github_api_key, github_url, organization
    )
    for repo in repos_json:
        if repo is not None and repo.get("url") in security_data:
            repo["securityAndAnalysis"] = security_data[repo["url"]]

    repo_data = upstream.transform(repos_json, direct, outside)
    upstream.enrich_dependencies_with_lockfile_versions(
        repo_data["dependencies"], github_api_key, github_url
    )
    upstream.load(neo4j_session, common_job_parameters, repo_data)

    pushedat_updates = [
        {"repo_url": repo["url"], "pushedat": repo["pushedAt"]}
        for repo in repos_json
        if repo is not None and repo.get("url") and repo.get("pushedAt")
    ]
    _write_repo_pushedat(neo4j_session, pushedat_updates)

    owner_org_id = next(
        (
            repo["owner_org_id"]
            for repo in repo_data["repos"]
            if repo.get("owner_org_id")
        ),
        f"https://github.com/{organization}",
    )
    upstream.migrate_dependency_graph_manifest_label(neo4j_session, owner_org_id)
    if repos_complete:
        upstream.cleanup_github_branches(
            neo4j_session, common_job_parameters, owner_org_id
        )
    else:
        logger.warning(
            "Skipping branch cleanup for %s because the repository listing was incomplete.",
            organization,
        )
    migration_params = {**common_job_parameters, "owner_org_id": owner_org_id}
    run_analysis_job(
        "github_branch_protection_rule_resource_edge_migration.json",
        neo4j_session,
        migration_params,
    )
    run_analysis_job(
        "github_dependency_manifest_resource_edge_migration.json",
        neo4j_session,
        migration_params,
    )
    if manifests_cleanup_safe and repos_complete:
        upstream.cleanup_github_manifests(
            neo4j_session, common_job_parameters, owner_org_id
        )
    else:
        logger.warning(
            "Skipping dependency manifest cleanup for %s because collection was incomplete.",
            organization,
        )
    if repos_complete:
        upstream.cleanup_branch_protection_rules(
            neo4j_session, common_job_parameters, owner_org_id
        )
    else:
        logger.warning(
            "Skipping branch protection cleanup for %s because the repository listing was incomplete.",
            organization,
        )
    if rulesets_cleanup_safe and repos_complete:
        upstream.cleanup_rulesets(neo4j_session, common_job_parameters, owner_org_id)
    else:
        logger.warning(
            "Skipping ruleset cleanup for %s because collection was incomplete.",
            organization,
        )

    return GitHubRepoSyncResult(
        repos=[repo for repo in repos_json if repo is not None],
        manifests=repo_data["manifests"],
        manifests_cleanup_safe=manifests_cleanup_safe and repos_complete,
        repo_pushedat_updates=pushedat_updates,
        repos_complete=repos_complete,
    )

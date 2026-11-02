"""Bounded-concurrency GitHub Actions collection with workflow bookmarks."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

import neo4j
import requests

import cartography.intel.github.actions as upstream
from cartography.client.core.tx import read_list_of_dicts_tx, run_write_query
from cartography.util import run_analysis_job, timeit

logger = logging.getLogger(__name__)


@dataclass
class _RepoActionsData:
    repo_name: str
    repo_url: str
    pushedat: str | None = None
    workflows_skipped: bool = False
    workflows_unavailable: bool = False
    enriched_workflows: list[dict[str, Any]] = field(default_factory=list)
    repo_actions: list[dict[str, Any]] = field(default_factory=list)
    environments: list[dict[str, Any]] = field(default_factory=list)
    repo_secrets: list[dict[str, Any]] = field(default_factory=list)
    repo_variables: list[dict[str, Any]] = field(default_factory=list)
    env_secrets: list[dict[str, Any]] = field(default_factory=list)
    env_variables: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ActionsSyncResult:
    workflows: list[dict[str, Any]]
    # Repos whose workflow listing was unavailable; their bookmarks must not advance.
    incomplete_repo_urls: list[str] = field(default_factory=list)


def _get_repos_from_graph(
    neo4j_session: neo4j.Session,
    organization: str,
) -> list[dict[str, Any]]:
    org_url = f"https://github.com/{organization}"
    return neo4j_session.execute_read(
        read_list_of_dicts_tx,
        """
        MATCH (org:GitHubOrganization {id: $org_url})<-[:OWNER]-(repo:GitHubRepository)
        RETURN repo.name AS name, repo.id AS url, repo.pushedat AS pushedat,
               repo.synced_pushedat AS synced_pushedat,
               repo.defaultbranch AS defaultbranch,
               repo.synced_defaultbranch AS synced_defaultbranch,
               repo.archived AS archived, repo.disabled AS disabled,
               [(repo)-[:HAS_SECRET]->(secret:GitHubActionsSecret) | secret.id]
                   AS secret_ids
        ORDER BY repo.name
        """,
        org_url=org_url,
    )


def _get_new_secret_ids(
    neo4j_session: neo4j.Session,
    secret_ids: list[str],
) -> list[str]:
    if not secret_ids:
        return []
    rows = neo4j_session.execute_read(
        read_list_of_dicts_tx,
        """
        UNWIND $secret_ids AS secret_id
        OPTIONAL MATCH (secret:GitHubActionsSecret {id: secret_id})
        WITH secret_id, secret WHERE secret IS NULL
        RETURN secret_id
        """,
        secret_ids=secret_ids,
    )
    return [row["secret_id"] for row in rows]


def _get_repo_workflows(
    token: str,
    api_url: str,
    organization: str,
    repo_name: str,
) -> list[dict[str, Any]]:
    """List workflows, raising on 403 instead of treating it as an empty listing."""
    base_url = upstream._get_rest_api_base_url(api_url)
    endpoint = f"/repos/{organization}/{repo_name}/actions/workflows"
    return upstream.fetch_all_rest_api_pages(
        token, base_url, endpoint, "workflows", raise_on_status=(403,)
    )


def _fetch_actions_for_repo(
    repo: dict[str, Any],
    organization: str,
    token: str,
    api_url: str,
    *,
    skip_unchanged_repos: bool,
    counter: list[int],
    counter_lock: threading.Lock,
    total: int,
) -> _RepoActionsData:
    data = _RepoActionsData(
        repo_name=repo["name"],
        repo_url=repo["url"],
        pushedat=repo.get("pushedat"),
    )
    # Settings are fetched first so new secrets can invalidate a workflow bookmark.
    environments = upstream.get_repo_environments(
        token, api_url, organization, repo["name"]
    ) or []
    if environments:
        data.environments = upstream.transform_environments(
            environments, organization, repo["name"]
        )
    secrets = upstream.get_repo_secrets(token, api_url, organization, repo["name"])
    if secrets:
        data.repo_secrets = upstream.transform_repo_secrets(
            secrets, organization, repo["name"]
        )
    variables = upstream.get_repo_variables(token, api_url, organization, repo["name"])
    if variables:
        data.repo_variables = upstream.transform_repo_variables(
            variables, organization, repo["name"]
        )
    for env in environments:
        name, env_id = env["name"], env["id"]
        env_secrets = upstream.get_env_secrets(
            token, api_url, organization, repo["name"], name
        )
        if env_secrets:
            data.env_secrets.extend(
                upstream.transform_env_secrets(
                    env_secrets, organization, repo["name"], name, env_id
                )
            )
        env_variables = upstream.get_env_variables(
            token, api_url, organization, repo["name"], name
        )
        if env_variables:
            data.env_variables.extend(
                upstream.transform_env_variables(
                    env_variables, organization, repo["name"], name, env_id
                )
            )

    known_secret_ids = set(repo.get("secret_ids") or [])
    has_new_repo_secrets = any(
        secret.get("id") not in known_secret_ids for secret in data.repo_secrets
    )
    skip_workflows = (
        skip_unchanged_repos
        and not has_new_repo_secrets
        and repo.get("pushedat") is not None
        and repo.get("synced_pushedat") is not None
        and repo["pushedat"] == repo["synced_pushedat"]
        and repo.get("defaultbranch") == repo.get("synced_defaultbranch")
    )
    if skip_workflows:
        data.workflows_skipped = True
    else:
        try:
            workflows = _get_repo_workflows(token, api_url, organization, repo["name"])
        except requests.exceptions.HTTPError:
            logger.warning(
                "Workflow listing unavailable for %s/%s; preserving existing workflows.",
                organization,
                repo["name"],
                exc_info=True,
            )
            data.workflows_unavailable = True
            workflows = []
        for workflow in upstream.transform_workflows(
            workflows or [], organization, repo["name"]
        ):
            content = None
            path = workflow.get("path")
            if path:
                content = upstream.get_workflow_content(
                    token, api_url, organization, repo["name"], path
                )
            parsed = upstream.parse_workflow_yaml(content) if content else None
            enriched = upstream.enrich_workflow_with_parsed_content(
                workflow, parsed, organization, repo["name"]
            )
            data.enriched_workflows.append(enriched)
            if parsed and workflow.get("id") is not None:
                data.repo_actions.extend(
                    upstream.transform_actions(
                        parsed, workflow["id"], organization, repo["name"]
                    )
                )

    with counter_lock:
        counter[0] += 1
        completed = counter[0]
    if completed == 1 or completed % 50 == 0 or completed == total:
        logger.info(
            "Actions fetch progress for org %s: %d/%d repos completed.",
            organization,
            completed,
            total,
        )
    return data


def _touch_skipped_workflows(
    neo4j_session: neo4j.Session,
    repo_urls: list[str],
    update_tag: int,
) -> None:
    if not repo_urls:
        return
    run_write_query(
        neo4j_session,
        """
        UNWIND $repo_urls AS repo_url
        MATCH (:GitHubRepository {id: repo_url})-[hw:HAS_WORKFLOW]->(wf:GitHubWorkflow)
        SET wf.lastupdated = $update_tag, hw.lastupdated = $update_tag
        WITH DISTINCT wf
        MATCH (:GitHubOrganization)-[res:RESOURCE]->(wf)
        SET res.lastupdated = $update_tag
        """,
        repo_urls=repo_urls,
        update_tag=update_tag,
    )
    run_write_query(
        neo4j_session,
        """
        UNWIND $repo_urls AS repo_url
        MATCH (:GitHubRepository {id: repo_url})-[:HAS_WORKFLOW]->(:GitHubWorkflow)
              -[rs:REFERENCES_SECRET]->(:GitHubActionsSecret)
        SET rs.lastupdated = $update_tag
        """,
        repo_urls=repo_urls,
        update_tag=update_tag,
    )
    run_write_query(
        neo4j_session,
        """
        UNWIND $repo_urls AS repo_url
        MATCH (:GitHubRepository {id: repo_url})-[:HAS_WORKFLOW]->(:GitHubWorkflow)
              -[ua:USES_ACTION]->(action:GitHubAction)
        SET action.lastupdated = $update_tag, ua.lastupdated = $update_tag
        WITH DISTINCT action
        MATCH (:GitHubOrganization)-[res:RESOURCE]->(action)
        SET res.lastupdated = $update_tag
        """,
        repo_urls=repo_urls,
        update_tag=update_tag,
    )


def _touch_archived_actions(
    neo4j_session: neo4j.Session,
    repo_urls: list[str],
    update_tag: int,
) -> None:
    """Preserve archived repositories' Actions graph without making API calls."""
    if not repo_urls:
        return
    run_write_query(
        neo4j_session,
        """
        UNWIND $repo_urls AS repo_url
        MATCH (repo:GitHubRepository {id: repo_url})-[rel]->(resource)
        WHERE type(rel) IN [
            'HAS_WORKFLOW', 'HAS_ENVIRONMENT', 'HAS_SECRET', 'HAS_VARIABLE'
        ]
        SET rel.lastupdated = $update_tag, resource.lastupdated = $update_tag
        WITH DISTINCT resource
        OPTIONAL MATCH (resource)-[child_rel]->(child)
        SET child_rel.lastupdated = $update_tag, child.lastupdated = $update_tag
        WITH DISTINCT resource, child
        UNWIND [resource, child] AS node
        WITH DISTINCT node WHERE node IS NOT NULL
        OPTIONAL MATCH (:GitHubOrganization)-[org_rel:RESOURCE]->(node)
        SET org_rel.lastupdated = $update_tag
        """,
        repo_urls=repo_urls,
        update_tag=update_tag,
    )


def _get_preserved_workflows(
    neo4j_session: neo4j.Session,
    repo_urls: list[str],
) -> list[dict[str, Any]]:
    if not repo_urls:
        return []
    return neo4j_session.execute_read(
        read_list_of_dicts_tx,
        """
        UNWIND $repo_urls AS repo_url
        MATCH (:GitHubRepository {id: repo_url})-[:HAS_WORKFLOW]->(wf:GitHubWorkflow)
        WHERE wf.repo_url IS NOT NULL AND wf.path IS NOT NULL
        RETURN wf.repo_url AS repo_url, wf.path AS path
        """,
        repo_urls=repo_urls,
    )


@timeit
def sync(
    neo4j_session: neo4j.Session,
    common_job_parameters: dict[str, Any],
    github_api_key: str,
    github_url: str,
    organization: str,
    *,
    parallel_workers: int = 1,
    skip_archived_repos: bool = False,
    skip_unchanged_repos: bool = False,
) -> ActionsSyncResult:
    """Sync Actions data; API work is parallel and all Neo4j writes are serial."""
    if parallel_workers < 1:
        raise ValueError("parallel_workers must be at least 1")
    org_url = f"https://github.com/{organization}"
    update_tag = common_job_parameters["UPDATE_TAG"]

    org_secrets = upstream.get_org_secrets(
        github_api_key, github_url, organization
    )
    if org_secrets:
        transformed_org_secrets = upstream.transform_org_secrets(
            org_secrets, organization
        )
        if skip_unchanged_repos and _get_new_secret_ids(
            neo4j_session,
            [secret["id"] for secret in transformed_org_secrets],
        ):
            logger.info(
                "New organization secrets in %s; refreshing all workflows to link them.",
                organization,
            )
            skip_unchanged_repos = False
        upstream.load_org_secrets(
            neo4j_session,
            transformed_org_secrets,
            update_tag,
            org_url,
        )
    org_variables = upstream.get_org_variables(
        github_api_key, github_url, organization
    )
    if org_variables:
        upstream.load_org_variables(
            neo4j_session,
            upstream.transform_org_variables(org_variables, organization),
            update_tag,
            org_url,
        )

    repos = _get_repos_from_graph(neo4j_session, organization)
    archived_urls = [
        repo["url"]
        for repo in repos
        if skip_archived_repos
        and (repo.get("archived") is True or repo.get("disabled") is True)
    ]
    active_repos = [repo for repo in repos if repo["url"] not in archived_urls]
    counter: list[int] = [0]
    counter_lock = threading.Lock()
    skipped_urls: list[str] = []
    incomplete_urls: list[str] = []
    workflows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=parallel_workers) as executor:
        futures = {
            executor.submit(
                _fetch_actions_for_repo,
                repo,
                organization,
                github_api_key,
                github_url,
                skip_unchanged_repos=skip_unchanged_repos,
                counter=counter,
                counter_lock=counter_lock,
                total=len(active_repos),
            ): repo
            for repo in active_repos
        }
        for future in as_completed(futures):
            data = future.result()
            if data.workflows_skipped:
                skipped_urls.append(data.repo_url)
            if data.workflows_unavailable:
                skipped_urls.append(data.repo_url)
                incomplete_urls.append(data.repo_url)
            # Secrets must exist before workflows so REFERENCES_SECRET edges match.
            if data.environments:
                upstream.load_environments(
                    neo4j_session, data.environments, update_tag, org_url
                )
            if data.repo_secrets:
                upstream.load_repo_secrets(
                    neo4j_session, data.repo_secrets, update_tag, org_url
                )
            if data.repo_variables:
                upstream.load_repo_variables(
                    neo4j_session, data.repo_variables, update_tag, org_url
                )
            if data.env_secrets:
                upstream.load_env_secrets(
                    neo4j_session, data.env_secrets, update_tag, org_url
                )
            if data.env_variables:
                upstream.load_env_variables(
                    neo4j_session, data.env_variables, update_tag, org_url
                )
            if data.enriched_workflows:
                upstream.load_workflows(
                    neo4j_session, data.enriched_workflows, update_tag, org_url
                )
                workflows.extend(data.enriched_workflows)
            if data.repo_actions:
                upstream.load_actions(
                    neo4j_session, data.repo_actions, update_tag, org_url
                )

    _touch_skipped_workflows(neo4j_session, skipped_urls, update_tag)
    _touch_archived_actions(neo4j_session, archived_urls, update_tag)
    preserved_urls = list(set(skipped_urls + archived_urls))
    workflows.extend(_get_preserved_workflows(neo4j_session, preserved_urls))

    cleanup_params = {**common_job_parameters, "org_url": org_url}
    run_analysis_job(
        "github_repo_actions_secret_resource_edge_migration.json",
        neo4j_session,
        cleanup_params,
    )
    upstream.cleanup_org_level(neo4j_session, cleanup_params)
    return ActionsSyncResult(workflows=workflows, incomplete_repo_urls=incomplete_urls)

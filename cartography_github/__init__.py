import base64
import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager

import neo4j

from cartography.config import Config
from cartography.intel.github import app_installations
from cartography.intel.github import cleanup_unscoped_github_resources
from cartography.intel.github import codeowners
from cartography.intel.github import container_image_attestations
from cartography.intel.github import container_image_tags
from cartography.intel.github import container_images
from cartography.intel.github import dependabot_alerts
from cartography.intel.github import external_identities
from cartography.intel.github import organizations
from cartography.intel.github import packages
from cartography.intel.github import personal_access_tokens
from cartography.intel.github import supply_chain
from cartography.intel.github import teams
from cartography.intel.github import users
from cartography.intel.github import webhooks
from cartography.intel.github.app_auth import make_credential
from cartography_github import actions
from cartography_github import commits
from cartography_github import repos
from cartography_github.auth import LockedCredential

logger = logging.getLogger(__name__)


@contextmanager
def _timed_stage(name: str, organization: str) -> Iterator[None]:
    started = time.monotonic()
    logger.info("Starting GitHub %s stage for %s", name, organization)
    try:
        yield
    except Exception:
        logger.exception(
            "GitHub %s stage for %s failed after %.1f seconds",
            name,
            organization,
            time.monotonic() - started,
        )
        raise
    logger.info(
        "Completed GitHub %s stage for %s in %.1f seconds",
        name,
        organization,
        time.monotonic() - started,
    )


def start_github_ingestion(
    neo4j_session: neo4j.Session,
    config: Config,
    *,
    parallel_workers: int = 4,
    incremental_sync: bool = True,
) -> None:
    """Run upstream GitHub stages with local incremental, parallel collection."""
    if parallel_workers < 1:
        raise ValueError("parallel_workers must be at least 1")
    if not config.github_config:
        raise ValueError("GitHub configuration is required")

    auth_data = json.loads(base64.b64decode(config.github_config).decode())
    job_parameters = {"UPDATE_TAG": config.update_tag}
    pending_bookmarks: list[dict[str, str]] = []
    processed_any_org = False
    started = time.monotonic()
    logger.info(
        "Starting local GitHub ingestion: incremental=%s, parallel_workers=%d",
        incremental_sync,
        parallel_workers,
    )

    for organization in auth_data["organization"]:
        token = LockedCredential(make_credential(organization))
        api_url = organization["url"]
        org_name = organization["name"]

        user_data, owners_data, org_data = users.get_organization(
            token, api_url, org_name
        )
        organizations.sync(
            neo4j_session, job_parameters, token, api_url, org_name, org_data
        )
        github_users = users.sync(
            neo4j_session, job_parameters, user_data, owners_data, org_data
        )
        external_identities.sync(
            neo4j_session, job_parameters, token, api_url, org_name
        )
        with _timed_stage("repositories", org_name):
            repo_result = repos.sync(
                neo4j_session,
                job_parameters,
                token,
                api_url,
                org_name,
                parallel_workers=parallel_workers,
                incremental_sync=incremental_sync,
            )
        personal_access_tokens.sync(
            neo4j_session, job_parameters, token, api_url, org_name
        )
        app_installations.sync(
            neo4j_session, job_parameters, token, api_url, org_name
        )
        webhooks.sync(
            neo4j_session,
            job_parameters,
            token,
            api_url,
            org_name,
            repo_result.repos,
            repos_complete=repo_result.repos_complete,
        )
        dependabot_alerts.sync(
            neo4j_session, job_parameters, token, api_url, org_name
        )
        github_teams = teams.sync_github_teams(
            neo4j_session, job_parameters, token, api_url, org_name
        )
        codeowners.sync(
            neo4j_session,
            job_parameters,
            token,
            api_url,
            org_name,
            repo_result.repos,
            repo_result.manifests,
            dependency_manifests_cleanup_safe=repo_result.manifests_cleanup_safe,
            github_users=github_users,
            github_teams=github_teams,
        )
        with _timed_stage("actions", org_name):
            all_workflows = actions.sync(
                neo4j_session,
                job_parameters,
                token,
                api_url,
                org_name,
                parallel_workers=parallel_workers,
                skip_archived_repos=incremental_sync,
                skip_unchanged_repos=incremental_sync,
            )

        repo_names = [
            repo["name"]
            for repo in repo_result.repos
            if not incremental_sync
            or not (repo.get("isArchived") or repo.get("isDisabled"))
        ]
        with _timed_stage("commits", org_name):
            commits.sync_github_commits(
                neo4j_session,
                token,
                api_url,
                org_name,
                repo_names,
                config.update_tag,
                config.github_commit_lookback_days,
                skip_stale_repos=incremental_sync,
            )

        with _timed_stage("packages", org_name):
            ghcr_result = packages.sync_packages(
                neo4j_session,
                token,
                api_url,
                org_name,
                config.update_tag,
                job_parameters,
            )
            if ghcr_result.cleanup_safe:
                manifests, _, tag_rows, observed_and_skipped = (
                    container_images.sync_container_images(
                        neo4j_session,
                        token,
                        api_url,
                        org_name,
                        ghcr_result.packages,
                        config.update_tag,
                        job_parameters,
                    )
                )
                container_image_tags.sync_container_image_tags(
                    neo4j_session,
                    org_name,
                    tag_rows,
                    config.update_tag,
                    job_parameters,
                )
                container_image_attestations.sync_container_image_attestations(
                    neo4j_session,
                    token,
                    api_url,
                    org_name,
                    manifests,
                    config.update_tag,
                    job_parameters,
                    additional_observed_digests=observed_and_skipped,
                )
        if repo_result.repos:
            with _timed_stage("supply-chain", org_name):
                supply_chain.sync(
                    neo4j_session,
                    token,
                    api_url,
                    org_name,
                    config.update_tag,
                    job_parameters,
                    repo_result.repos,
                    workflows=all_workflows,
                )

        if incremental_sync and repo_result.repos_complete:
            pending_bookmarks.extend(repo_result.repo_pushedat_updates)
        processed_any_org = True

    if processed_any_org:
        cleanup_unscoped_github_resources(neo4j_session, job_parameters)
        if pending_bookmarks:
            repos._write_synced_pushedat(neo4j_session, pending_bookmarks)
    logger.info(
        "Completed local GitHub ingestion in %.1f seconds", time.monotonic() - started
    )

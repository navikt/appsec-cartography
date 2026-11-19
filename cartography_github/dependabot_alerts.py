"""Refresh live repository alerts without using push activity as a filter."""

import logging
from typing import Any

import neo4j

import cartography.intel.github.dependabot_alerts as upstream
from cartography.intel.github.util import github_org_url
from cartography.models.github.dependabot_alerts import GitHubDependabotAlertSchema
from cartography_github.incremental import touch_skipped_repo_resources

logger = logging.getLogger(__name__)


def sync(
    neo4j_session: neo4j.Session,
    common_job_parameters: dict[str, Any],
    github_api_key: str,
    github_url: str,
    organization: str,
    *,
    excluded_repo_urls: set[str] | None = None,
) -> None:
    org_url = github_org_url(github_url, organization)
    update_tag = common_job_parameters["UPDATE_TAG"]
    fetch_result = upstream.get(github_api_key, github_url, organization)
    if not fetch_result.cleanup_safe:
        logger.warning(
            "Skipping Dependabot alert loading and cleanup for %s because collection was incomplete.",
            organization,
        )
        return

    alerts = fetch_result.alerts
    if excluded_repo_urls is not None:
        alerts = []
        for alert in fetch_result.alerts:
            repo = alert.get("repository") or {}
            if (
                repo.get("html_url") in excluded_repo_urls
                or repo.get("archived")
                or repo.get("disabled")
            ):
                continue
            alerts.append(alert)
    transformed = upstream.transform(alerts)
    upstream.load_users(neo4j_session, transformed["users"], update_tag)
    upstream.load_alerts(neo4j_session, transformed["alerts"], update_tag, org_url)
    touch_skipped_repo_resources(
        neo4j_session,
        excluded_repo_urls or set(),
        GitHubDependabotAlertSchema(),
        update_tag,
        org_url,
    )
    upstream.cleanup(neo4j_session, common_job_parameters, org_url)

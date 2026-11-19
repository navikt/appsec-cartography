"""Archive-aware webhook collection using upstream loaders and cleanup."""

from typing import Any

import neo4j

import cartography.intel.github.webhooks as upstream
from cartography.intel.github.util import github_org_url
from cartography.models.github.webhooks import GitHubWebhookSchema
from cartography_github.incremental import touch_skipped_repo_resources


def sync(
    neo4j_session: neo4j.Session,
    common_job_parameters: dict[str, Any],
    token: Any,
    api_url: str,
    organization: str,
    repos: list[dict[str, Any]],
    repos_complete: bool = True,
    *,
    excluded_repo_urls: set[str] | None = None,
) -> None:
    excluded = excluded_repo_urls or set()
    touch_skipped_repo_resources(
        neo4j_session,
        excluded,
        GitHubWebhookSchema(),
        common_job_parameters["UPDATE_TAG"],
        github_org_url(api_url, organization),
    )
    upstream.sync(
        neo4j_session,
        common_job_parameters,
        token,
        api_url,
        organization,
        [repo for repo in repos if repo.get("id") not in excluded],
        repos_complete=repos_complete,
    )

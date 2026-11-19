"""Archive-aware CODEOWNERS collection using upstream parsing and cleanup."""

from typing import Any

import neo4j

import cartography.intel.github.codeowners as upstream
from cartography.intel.github.util import github_org_url
from cartography.models.github.codeowners import (
    DependencyGraphManifestToCodeOwnerRuleMatchLink,
    GitHubCodeOwnerRuleSchema,
)
from cartography_github.incremental import touch_skipped_repo_resources


def sync(
    neo4j_session: neo4j.Session,
    common_job_parameters: dict[str, Any],
    github_api_key: str,
    github_url: str,
    organization: str,
    repositories: list[dict[str, Any]],
    dependency_manifests: list[dict[str, Any]],
    *,
    dependency_manifests_cleanup_safe: bool = True,
    github_users: list[dict[str, Any]] | None = None,
    github_teams: list[dict[str, Any]] | None = None,
    excluded_repo_urls: set[str] | None = None,
) -> None:
    excluded = excluded_repo_urls or set()
    touch_skipped_repo_resources(
        neo4j_session,
        excluded,
        GitHubCodeOwnerRuleSchema(),
        common_job_parameters["UPDATE_TAG"],
        github_org_url(github_url, organization),
        matchlinks=(DependencyGraphManifestToCodeOwnerRuleMatchLink(),),
    )
    upstream.sync(
        neo4j_session,
        common_job_parameters,
        github_api_key,
        github_url,
        organization,
        [repo for repo in repositories if repo.get("id") not in excluded],
        dependency_manifests,
        dependency_manifests_cleanup_safe=dependency_manifests_cleanup_safe,
        github_users=github_users,
        github_teams=github_teams,
    )

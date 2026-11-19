"""Archive-aware orchestration of the pinned upstream supply-chain stages."""

import logging
from typing import Any

import neo4j

import cartography.intel.github.supply_chain as upstream
from cartography.client.core.tx import run_write_query
from cartography.models.github.packaged_matchlink import (
    GitHubRepoDockerfilePackagedFromMatchLink,
    GitHubRepoPackageOwnerPackagedFromMatchLink,
    GitHubRepoProvenancePackagedFromMatchLink,
    ImagePackagedByWorkflowMatchLink,
)

logger = logging.getLogger(__name__)


def sync(
    neo4j_session: neo4j.Session,
    token: str,
    api_url: str,
    organization: str,
    update_tag: int,
    common_job_parameters: dict[str, Any],
    repos: list[dict[str, Any]],
    workflows: list[dict[str, Any]] | None = None,
    image_limit: int | None = None,
    min_match_confidence: float = 0.5,
    *,
    excluded_repo_urls: set[str] | None = None,
) -> None:
    if not excluded_repo_urls:
        upstream.sync(
            neo4j_session,
            token,
            api_url,
            organization,
            update_tag,
            common_job_parameters,
            repos,
            workflows=workflows,
            image_limit=image_limit,
            min_match_confidence=min_match_confidence,
        )
        return

    logger.info(
        "Syncing supply chain for %s, excluding %d archived/disabled repositories.",
        organization,
        len(excluded_repo_urls),
    )
    repos = [repo for repo in repos if repo.get("url") not in excluded_repo_urls]
    workflows = [
        workflow
        for workflow in workflows or []
        if workflow.get("repo_url") not in excluded_repo_urls
    ]
    run_write_query(
        neo4j_session,
        """
        UNWIND $repo_urls AS repo_url
        MATCH (:GitHubRepository {id: repo_url})-[:HAS_WORKFLOW*0..1]->(target)
              <-[rel:PACKAGED_FROM|PACKAGED_BY]-(:Image)
        WHERE rel._sub_resource_label = 'GitHubOrganization'
          AND rel._sub_resource_id = $organization
        SET rel.lastupdated = $update_tag
        """,
        repo_urls=sorted(excluded_repo_urls),
        organization=organization,
        update_tag=update_tag,
    )
    workflow_data = [
        {"repo_url": wf["repo_url"], "workflow_path": wf["path"]}
        for wf in workflows
        if wf.get("repo_url") and wf.get("path")
    ]
    if workflow_data:
        upstream.load_matchlinks(
            neo4j_session,
            ImagePackagedByWorkflowMatchLink(),
            workflow_data,
            lastupdated=update_tag,
            _sub_resource_label="GitHubOrganization",
            _sub_resource_id=organization,
        )
    provenance_data = [
        {
            "repo_url": repo["url"],
            "match_method": "provenance",
            "dockerfile_path": None,
            "confidence": 1.0,
            "matched_commands": 0,
            "total_commands": 0,
            "command_similarity": 1.0,
        }
        for repo in repos
        if repo.get("url")
    ]
    if provenance_data:
        upstream.load_matchlinks(
            neo4j_session,
            GitHubRepoProvenancePackagedFromMatchLink(),
            provenance_data,
            lastupdated=update_tag,
            _sub_resource_label="GitHubOrganization",
            _sub_resource_id=organization,
        )

    unmatched = upstream.get_unmatched_container_images_with_history(
        neo4j_session,
        organization,
        update_tag,
        limit=image_limit,
    )
    for fetch_images in (
        upstream.get_unmatched_gcp_images_with_history,
        upstream.get_unmatched_scaleway_images_with_history,
    ):
        remaining_limit = (
            None if image_limit is None else max(image_limit - len(unmatched), 0)
        )
        if remaining_limit != 0:
            unmatched += fetch_images(
                neo4j_session,
                sub_resource_label="GitHubOrganization",
                sub_resource_id=organization,
                update_tag=update_tag,
                limit=remaining_limit,
            )
    if unmatched:
        base_url = api_url.removesuffix("/graphql")
        dockerfiles = upstream.get_dockerfiles_for_repos(
            token,
            repos,
            organization,
            base_url,
        )
        if dockerfiles:
            matches = upstream.match_images_to_dockerfiles(
                unmatched,
                dockerfiles,
                min_confidence=min_match_confidence,
            )
            if matches:
                matchlink_data = upstream.transform_matches_for_matchlink(
                    matches,
                    "repo_url",
                )
                if matchlink_data:
                    upstream.load_matchlinks(
                        neo4j_session,
                        GitHubRepoDockerfilePackagedFromMatchLink(),
                        matchlink_data,
                        lastupdated=update_tag,
                        _sub_resource_label="GitHubOrganization",
                        _sub_resource_id=organization,
                    )

    package_owner_data = [
        entry
        for entry in upstream._get_unmatched_ghcr_image_owner_repos(
            neo4j_session,
            organization,
            update_tag,
        )
        if entry["repo_url"] not in excluded_repo_urls
    ]
    if package_owner_data:
        for entry in package_owner_data:
            entry.update(
                match_method="package_owner_repo",
                dockerfile_path=None,
                confidence=upstream._PACKAGE_OWNER_FALLBACK_CONFIDENCE,
                matched_commands=0,
                total_commands=0,
                command_similarity=0.0,
            )
        upstream.load_matchlinks(
            neo4j_session,
            GitHubRepoPackageOwnerPackagedFromMatchLink(),
            package_owner_data,
            lastupdated=update_tag,
            _sub_resource_label="GitHubOrganization",
            _sub_resource_id=organization,
        )

    for schema in (
        ImagePackagedByWorkflowMatchLink(),
        GitHubRepoProvenancePackagedFromMatchLink(),
        GitHubRepoDockerfilePackagedFromMatchLink(),
        GitHubRepoPackageOwnerPackagedFromMatchLink(),
    ):
        upstream.GraphJob.from_matchlink(
            schema,
            "GitHubOrganization",
            organization,
            update_tag,
        ).run(neo4j_session)
    upstream.run_typed_analysis_job(
        upstream.SUPPLY_CHAIN_SOURCE_FILE,
        neo4j_session,
        common_job_parameters,
    )

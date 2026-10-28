import logging
from pathlib import Path
from typing import Any

import neo4j

import cartography_nais.teams
import cartography_nais.workloads
from cartography.client.core.tx import load
from cartography.config import Config
from cartography_nais.client import NaisGraphQLClient
from cartography_nais.models.tenant import NaisTenantSchema
from cartography.util import run_analysis_job
from cartography.util import timeit

logger = logging.getLogger(__name__)


def _load_tenant(
    neo4j_session: neo4j.Session,
    tenant_id: str,
    update_tag: int,
) -> None:
    load(
        neo4j_session,
        NaisTenantSchema(),
        [{"id": tenant_id}],
        lastupdated=update_tag,
    )


@timeit
def start_nais_ingestion(
    neo4j_session: neo4j.Session,
    config: Config,
    *,
    base_url: str,
    token_path: str,
) -> None:
    """
    Entry point for NAIS ingestion. Called by the cartography sync framework.
    """
    if not Path(token_path).read_text().strip():
        raise ValueError(f"Nais token file is empty: {token_path}")

    logger.info("Starting NAIS sync")
    tenant_id = base_url
    common_job_parameters: dict[str, Any] = {
        "UPDATE_TAG": config.update_tag,
        "TENANT_ID": tenant_id,
        "NAIS_TENANT_ID": tenant_id,
    }

    client = NaisGraphQLClient(
        token_path=token_path,
        base_url=base_url,
    )

    _load_tenant(neo4j_session, tenant_id, config.update_tag)

    cartography_nais.teams.sync(
        neo4j_session,
        client,
        tenant_id,
        config.update_tag,
        common_job_parameters,
    )

    cartography_nais.workloads.sync(
        neo4j_session,
        client,
        tenant_id,
        config.update_tag,
        common_job_parameters,
    )

    # Jobs are executed in dependency order:
    # 1. active_deployment  — sets ACTIVE_DEPLOYMENT edge (prerequisite for DEPLOYED_BY)
    # 2. image_link         — tag-based RUNS_IMAGE fallback (runs before digest variant)
    # 3. image_digest_link  — digest-based RUNS_IMAGE (supplements tag-based match)
    # 4. gar_link           — RUNS_GAR_IMAGE for GAR images
    # 5. deployed_by        — KubernetesContainer -[:DEPLOYED_BY]-> NaisDeployment
    #                         (requires RUNS_IMAGE + ACTIVE_DEPLOYMENT)
    # 6. built_from_repo    — KubernetesContainer -[:BUILT_FROM]-> GitHubRepository
    #                         (requires DEPLOYED_BY + DEPLOYED_FROM)
    # 7. ownership          — NaisTeam -[:RESPONSIBLE_FOR]-> KubernetesPod
    #                         (requires RUNS_IMAGE)
    _analysis_job_order = [
        "nais_active_deployment.json",
        "nais_image_link.json",
        "nais_image_digest_link.json",
        "nais_gar_link.json",
        "nais_deployed_by.json",
        "nais_built_from_repo.json",
        "nais_ownership.json",
    ]
    for job_file in _analysis_job_order:
        run_analysis_job(
            job_file,
            neo4j_session,
            common_job_parameters,
            package="cartography_nais.analysis",
        )

    logger.info("Completed NAIS sync")

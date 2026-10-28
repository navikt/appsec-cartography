import logging
from typing import Any

import neo4j

from cartography.client.core.tx import load
from cartography.client.core.tx import load_matchlinks
from cartography.graph.job import GraphJob
from cartography_nais.client import NaisGraphQLClient
from cartography_nais.models.workload import NaisAppSchema
from cartography_nais.models.workload import NaisDeploymentSchema
from cartography_nais.models.workload import NaisDeploymentToGitHubUserRel
from cartography.util import timeit

logger = logging.getLogger(__name__)

ENVIRONMENTS_QUERY = """
query GetEnvironments {
  environments {
    nodes { name }
  }
}
"""

WORKLOADS_QUERY = """
query GetWorkloads($env: String!, $first: Int!, $cursor: Cursor, $deploymentLimit: Int!) {
  environment(name: $env) {
    workloads(first: $first, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        ... on Application {
          __typename
          id
          name
          appState: state
          team { slug }
          teamEnvironment {
            gcpProjectID
            environment { name }
          }
          image { name tag digest }
          ingresses { url }
          instances(first: 50) {
            nodes {
              status { state }
              image {
                digest
                workloadReferences {
                  nodes {
                    workload {
                      deployments(first: $deploymentLimit) {
                        nodes {
                          id
                          repository
                          commitSha
                          deployerUsername
                        }
                      }
                    }
                  }
                }
              }
            }
          }
          deployments(first: $deploymentLimit) {
            nodes {
              id
              createdAt
              teamSlug
              environmentName
              repository
              deployerUsername
              commitSha
              triggerUrl
              statuses(first: 1) {
                nodes { state }
              }
            }
          }
        }
        ... on Job {
          __typename
          id
          name
          jobState: state
          team { slug }
          teamEnvironment {
            gcpProjectID
            environment { name }
          }
          image { name tag digest }
          deployments(first: $deploymentLimit) {
            nodes {
              id
              createdAt
              teamSlug
              environmentName
              repository
              deployerUsername
              commitSha
              triggerUrl
              statuses(first: 1) {
                nodes { state }
              }
            }
          }
        }
      }
    }
  }
}
"""


def get_environments(client: NaisGraphQLClient) -> list[str]:
    data = client.query(ENVIRONMENTS_QUERY)
    return [environment["name"] for environment in data["environments"]["nodes"]]


def get_workloads(
    client: NaisGraphQLClient,
    deployment_limit: int = 10,
) -> list[dict[str, Any]]:
    environments = get_environments(client)
    logger.info(
        "NAIS workloads: fetching workloads for %d environments", len(environments)
    )
    workloads = []
    for idx, env in enumerate(environments, start=1):
        results = client.paginate(
            WORKLOADS_QUERY,
            ["environment", "workloads"],
            variables={"env": env, "deploymentLimit": deployment_limit},
        )
        workloads.extend(results)
        logger.info(
            "NAIS workloads: environment %d/%d '%s' — %d workloads (total so far: %d)",
            idx,
            len(environments),
            env,
            len(results),
            len(workloads),
        )
    return workloads


def transform_workloads(
    raw: list[dict[str, Any]],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Return (apps, deployments, image_deployment_links) extracted from raw workload nodes.

    Deployments are fetched inline per workload (most-recent-first).
    The first deployment per workload whose latest status is SUCCESS is
    flagged is_active=True; all others are False (kept as read-only metadata).

    has_running_instance reflects Kubernetes reality:
    - Applications: True if at least one instance reports state RUNNING.
    - Jobs: always True — jobs are scheduled/triggered workloads that will
      run eventually, so they are considered perpetually active if they exist
      in NAIS regardless of their last run state.

    image_deployment_links contains mappings of image digest to deployment ID,
    extracted from instance-level workloadReferences. These are used to create
    KubernetesContainer -[:DEPLOYED_BY]-> NaisDeployment edges via analysis jobs.
    Entries with no digest are omitted.
    """
    apps = []
    all_deployments: list[dict] = []
    image_deployment_links: list[dict] = []
    seen_image_deployment_pairs: set[tuple[str, str]] = set()

    for w in raw:
        team = w.get("team") or {}
        team_env = w.get("teamEnvironment") or {}
        env = team_env.get("environment") or {}
        image = w.get("image") or {}
        ingress_urls = [i["url"] for i in (w.get("ingresses") or []) if i.get("url")]
        workload_type = w.get("__typename")

        # Applications: check live Kubernetes instances; Jobs: always active.
        if workload_type == "Application":
            instances = (w.get("instances") or {}).get("nodes") or []
            has_running_instance = any(
                (i.get("status") or {}).get("state") == "RUNNING" for i in instances
            )
        else:
            has_running_instance = True
            instances = []

        app_id = w["id"]
        image_digest = image.get("digest")
        apps.append(
            {
                "id": app_id,
                "name": w.get("name"),
                "workload_type": workload_type,
                "team_slug": team.get("slug"),
                "environment": env.get("name"),
                "gcp_project_id": team_env.get("gcpProjectID"),
                "image_name": image.get("name"),
                "image_tag": image.get("tag"),
                "image_digest": image_digest,
                "state": w.get("appState") or w.get("jobState"),
                "ingresses": ingress_urls,
                "has_running_instance": has_running_instance,
            }
        )

        # Extract image->deployment provenance from instance workloadReferences.
        # Each running instance carries the digest of the image it is actually
        # running and, via workloadReferences, the deployment(s) that produced it.
        # We deduplicate on (digest, deployment_id) so we don't emit duplicates
        # when multiple instances share the same image.
        for inst in instances:
            inst_image = inst.get("image") or {}
            inst_digest = inst_image.get("digest")
            if not inst_digest:
                continue
            wl_refs = (inst_image.get("workloadReferences") or {}).get("nodes") or []
            for ref in wl_refs:
                workload = ref.get("workload") or {}
                dep_nodes = (workload.get("deployments") or {}).get("nodes") or []
                for dep in dep_nodes:
                    dep_id = dep.get("id")
                    if not dep_id:
                        continue
                    pair = (inst_digest, dep_id)
                    if pair in seen_image_deployment_pairs:
                        continue
                    seen_image_deployment_pairs.add(pair)
                    image_deployment_links.append(
                        {
                            "image_digest": inst_digest,
                            "deployment_id": dep_id,
                        }
                    )

        raw_deps = (w.get("deployments") or {}).get("nodes") or []
        active_found = False
        for d in raw_deps:
            statuses = (d.get("statuses") or {}).get("nodes") or []
            latest_status = statuses[0]["state"] if statuses else None

            is_active = False
            if not active_found and latest_status == "SUCCESS":
                is_active = True
                active_found = True

            repo = d.get("repository")
            # Fall back to parent workload team slug if not on the deployment node
            team_slug = d.get("teamSlug") or team.get("slug")
            all_deployments.append(
                {
                    "id": d["id"],
                    "created_at": d.get("createdAt"),
                    "team_slug": team_slug,
                    "environment_name": d.get("environmentName"),
                    "repository": repo,
                    "repository_url": f"https://github.com/{repo}" if repo else None,
                    "deployer_username": d.get("deployerUsername"),
                    "commit_sha": d.get("commitSha"),
                    "trigger_url": d.get("triggerUrl"),
                    "latest_status": latest_status,
                    "is_active": is_active,
                    "app_id": app_id,
                }
            )

    return apps, all_deployments, image_deployment_links


@timeit
def load_apps(
    neo4j_session: neo4j.Session,
    apps: list[dict],
    tenant_id: str,
    update_tag: int,
) -> None:
    load(
        neo4j_session,
        NaisAppSchema(),
        apps,
        lastupdated=update_tag,
        NAIS_TENANT_ID=tenant_id,
    )


@timeit
def load_deployments(
    neo4j_session: neo4j.Session,
    deployments: list[dict],
    tenant_id: str,
    update_tag: int,
) -> None:
    load(
        neo4j_session,
        NaisDeploymentSchema(),
        deployments,
        lastupdated=update_tag,
        NAIS_TENANT_ID=tenant_id,
    )


@timeit
def load_deployer_links(
    neo4j_session: neo4j.Session,
    deployments: list[dict],
    tenant_id: str,
    update_tag: int,
) -> None:
    mapping = [
        {"deployment_id": d["id"], "deployer_username": d["deployer_username"]}
        for d in deployments
        if d.get("deployer_username")
    ]
    load_matchlinks(
        neo4j_session,
        NaisDeploymentToGitHubUserRel(),
        mapping,
        lastupdated=update_tag,
        _sub_resource_label="NaisTenant",
        _sub_resource_id=tenant_id,
    )


@timeit
def cleanup(
    neo4j_session: neo4j.Session,
    common_job_parameters: dict[str, Any],
) -> None:
    GraphJob.from_node_schema(NaisAppSchema(), common_job_parameters).run(neo4j_session)
    GraphJob.from_node_schema(NaisDeploymentSchema(), common_job_parameters).run(
        neo4j_session
    )
    GraphJob.from_matchlink(
        NaisDeploymentToGitHubUserRel(),
        "NaisTenant",
        common_job_parameters["NAIS_TENANT_ID"],
        common_job_parameters["UPDATE_TAG"],
    ).run(neo4j_session)


@timeit
def sync(
    neo4j_session: neo4j.Session,
    client: NaisGraphQLClient,
    tenant_id: str,
    update_tag: int,
    common_job_parameters: dict[str, Any],
    deployment_limit: int = 10,
    _workloads_raw: list[dict[str, Any]] | None = None,
) -> None:
    logger.info("Syncing NAIS workloads")
    raw_workloads = (
        _workloads_raw
        if _workloads_raw is not None
        else get_workloads(client, deployment_limit)
    )
    apps, deployments, image_deployment_links = transform_workloads(raw_workloads)
    logger.info(
        "NAIS workloads: %d workloads, %d deployments, %d image-deployment links to load",
        len(apps),
        len(deployments),
        len(image_deployment_links),
    )
    load_apps(neo4j_session, apps, tenant_id, update_tag)
    load_deployments(neo4j_session, deployments, tenant_id, update_tag)
    load_deployer_links(neo4j_session, deployments, tenant_id, update_tag)
    cleanup(neo4j_session, common_job_parameters)
    logger.info("NAIS workloads sync complete")

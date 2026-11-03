import logging
from typing import Any

import neo4j

from cartography.client.core.tx import load
from cartography.client.core.tx import load_matchlinks
from cartography.graph.job import GraphJob
from cartography_nais.client import NaisGraphQLClient
from cartography_nais.models.workload import NaisAppSchema
from cartography_nais.models.workload import NaisAppToActiveDeploymentMatchLink
from cartography_nais.models.workload import NaisAppToDeploymentMatchLink
from cartography_nais.models.workload import NaisDeploymentSchema
from cartography_nais.models.workload import NaisDeploymentToGitHubUserRel
from cartography.util import timeit

logger = logging.getLogger(__name__)

DEPLOYMENT_FRAGMENT = """
fragment DeploymentFields on Deployment {
  id
  createdAt
  teamSlug
  environmentName
  repository
  deployerUsername
  commitSha
  triggerUrl
  resources(first: 20) {
    pageInfo { hasNextPage endCursor }
    nodes { kind name }
  }
  statuses(first: 20) {
    pageInfo { hasNextPage endCursor }
    nodes { state createdAt }
  }
}
"""

ENVIRONMENTS_QUERY = """
query GetEnvironments {
  environments {
    nodes { name }
  }
}
"""

# Application and Job declare differently typed `state` and `authIntegrations`,
# so they are aliased per type.
WORKLOADS_QUERY = (
    """
query GetWorkloads($env: String!, $first: Int!, $cursor: Cursor) {
  environment(name: $env) {
    workloads(first: $first, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        __typename
        id
        name
        deletionStartedAt
        team { slug }
        teamEnvironment { id environment { name } }
        image { name tag digest }
        deployments(first: 20) {
          pageInfo { hasNextPage endCursor }
          nodes { ...DeploymentFields }
        }
        ... on Application {
          appState: state
          ingresses { url type }
          appAuth: authIntegrations {
            __typename
            ... on AuthIntegration { name }
          }
        }
        ... on Job {
          jobState: state
          schedule { expression }
          jobAuth: authIntegrations {
            __typename
            ... on AuthIntegration { name }
          }
        }
      }
    }
  }
}
"""
    + DEPLOYMENT_FRAGMENT
)

def get_environments(client: NaisGraphQLClient) -> list[str]:
    data = client.query(ENVIRONMENTS_QUERY)
    return [environment["name"] for environment in data["environments"]["nodes"]]


def _complete_deployment(client: NaisGraphQLClient, deployment: dict) -> dict:
    for field, selection in (("resources", "kind name"), ("statuses", "state createdAt")):
        deployment[field] = client.complete_connection(
            deployment.get(field),
            node_id=deployment["id"],
            node_type="Deployment",
            field=field,
            selection=selection,
        )
    return deployment


def get_workloads(client: NaisGraphQLClient) -> list[dict[str, Any]]:
    environments = get_environments(client)
    logger.info("NAIS workloads: fetching %d environments", len(environments))
    workloads = []
    for env in environments:
        results = client.paginate(
            WORKLOADS_QUERY,
            ["environment", "workloads"],
            variables={"env": env},
            page_size=20,
        )
        for workload in results:
            # Workload.deployments has no ordering argument, so fetch the full history.
            deployments = client.complete_connection(
                workload.get("deployments"),
                node_id=workload["id"],
                node_type=workload["__typename"],
                field="deployments",
                selection="...DeploymentFields",
                fragments=DEPLOYMENT_FRAGMENT,
            )
            workload["deployments"] = [
                _complete_deployment(client, d) for d in deployments
            ]
        workloads.extend(results)
        logger.info("NAIS workloads: %s has %d workloads", env, len(results))
    return workloads


def _latest_status(statuses: list[dict]) -> dict:
    return max(statuses, key=lambda s: s.get("createdAt") or "", default={})


def _transform_deployment(raw: dict) -> dict:
    latest = _latest_status(raw.get("statuses") or [])
    repo = raw.get("repository")
    return {
        "id": raw["id"],
        "created_at": raw.get("createdAt"),
        "team_slug": raw.get("teamSlug"),
        "environment_name": raw.get("environmentName"),
        "repository": repo,
        "repository_url": f"https://github.com/{repo}" if repo else None,
        "deployer_username": raw.get("deployerUsername"),
        "commit_sha": raw.get("commitSha"),
        "trigger_url": raw.get("triggerUrl"),
        "latest_status": latest.get("state"),
        "latest_status_at": latest.get("createdAt"),
        "resources": [
            f"{r.get('kind')}/{r.get('name')}" for r in raw.get("resources") or []
        ],
    }


def _auth_integrations(workload: dict) -> list[str]:
    integrations = workload.get("appAuth") or workload.get("jobAuth") or []
    return sorted(
        f"{i['__typename'].removesuffix('AuthIntegration')}:{i.get('name')}"
        for i in integrations
    )


def transform(
    raw_workloads: list[dict[str, Any]],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """
    Return (apps, deployments, app_deployment_links, active_deployment_links).

    The active deployment is the newest successful deployment of each workload.
    """
    apps = []
    deployments: dict[str, dict] = {}
    links: set[tuple[str, str]] = set()

    for w in raw_workloads:
        workload_type = w["__typename"]
        team_slug = (w.get("team") or {}).get("slug")
        team_env = w.get("teamEnvironment") or {}
        environment = (team_env.get("environment") or {}).get("name")
        image = w.get("image") or {}
        schedule = (w.get("schedule") or {}).get("expression")
        ingresses = w.get("ingresses") or []
        app_id = w["id"]
        apps.append(
            {
                "id": app_id,
                "name": w["name"],
                "workload_type": workload_type,
                "team_slug": team_slug,
                "environment": environment,
                "team_environment_id": team_env.get("id"),
                "image_name": image.get("name"),
                "image_tag": image.get("tag"),
                "image_digest": image.get("digest"),
                "state": w.get("appState") or w.get("jobState"),
                "ingresses": [i["url"] for i in ingresses if i.get("url")],
                "ingress_types": sorted({i["type"] for i in ingresses if i.get("type")}),
                "auth_integrations": _auth_integrations(w),
                "schedule": schedule,
                "deletion_started_at": w.get("deletionStartedAt"),
                "k8s_deployment_name": (
                    w["name"] if workload_type == "Application" else None
                ),
                # Unscheduled Naisjobs create Jobs directly; they have no stable controller name.
                "k8s_cronjob_name": w["name"] if schedule else None,
            }
        )
        for d in w.get("deployments") or []:
            deployments[d["id"]] = _transform_deployment(d)
            links.add((app_id, d["id"]))

    deployments_by_app: dict[str, list[dict]] = {}
    for app_id, deployment_id in links:
        deployments_by_app.setdefault(app_id, []).append(deployments[deployment_id])

    active_links = []
    for app in apps:
        app_deployments = sorted(
            deployments_by_app.get(app["id"], []),
            key=lambda d: d["created_at"] or "",
            reverse=True,
        )
        app["latest_deployment_status"] = (
            app_deployments[0]["latest_status"] if app_deployments else None
        )
        active = next(
            (d for d in app_deployments if d["latest_status"] == "SUCCESS"), None
        )
        if active:
            active_links.append({"app_id": app["id"], "deployment_id": active["id"]})

    app_deployment_links = [
        {"app_id": app_id, "deployment_id": deployment_id}
        for app_id, deployment_id in sorted(links)
    ]
    return apps, list(deployments.values()), app_deployment_links, active_links


@timeit
def load_workloads(
    neo4j_session: neo4j.Session,
    apps: list[dict],
    deployments: list[dict],
    app_deployment_links: list[dict],
    active_links: list[dict],
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
    load(
        neo4j_session,
        NaisDeploymentSchema(),
        deployments,
        lastupdated=update_tag,
        NAIS_TENANT_ID=tenant_id,
    )
    deployer_links = [
        {"deployment_id": d["id"], "deployer_username": d["deployer_username"]}
        for d in deployments
        if d.get("deployer_username")
    ]
    for rel_schema, mapping in (
        (NaisAppToDeploymentMatchLink(), app_deployment_links),
        (NaisAppToActiveDeploymentMatchLink(), active_links),
        (NaisDeploymentToGitHubUserRel(), deployer_links),
    ):
        load_matchlinks(
            neo4j_session,
            rel_schema,
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
    for rel_schema in (
        NaisAppToDeploymentMatchLink(),
        NaisAppToActiveDeploymentMatchLink(),
        NaisDeploymentToGitHubUserRel(),
    ):
        GraphJob.from_matchlink(
            rel_schema,
            "NaisTenant",
            common_job_parameters["NAIS_TENANT_ID"],
            common_job_parameters["UPDATE_TAG"],
        ).run(neo4j_session)
    for schema in (NaisDeploymentSchema(), NaisAppSchema()):
        GraphJob.from_node_schema(schema, common_job_parameters).run(neo4j_session)


@timeit
def sync(
    neo4j_session: neo4j.Session,
    client: NaisGraphQLClient,
    tenant_id: str,
    update_tag: int,
    common_job_parameters: dict[str, Any],
    _workloads_raw: list[dict[str, Any]] | None = None,
) -> None:
    logger.info("Syncing NAIS workloads and deployments")
    raw_workloads = (
        _workloads_raw if _workloads_raw is not None else get_workloads(client)
    )
    apps, deployments, app_deployment_links, active_links = transform(raw_workloads)
    logger.info(
        "NAIS workloads: %d workloads, %d deployments, %d workload links, "
        "%d workloads without an active deployment",
        len(apps),
        len(deployments),
        len(app_deployment_links),
        len(apps) - len(active_links),
    )
    load_workloads(
        neo4j_session,
        apps,
        deployments,
        app_deployment_links,
        active_links,
        tenant_id,
        update_tag,
    )
    cleanup(neo4j_session, common_job_parameters)
    logger.info("NAIS workloads sync complete")

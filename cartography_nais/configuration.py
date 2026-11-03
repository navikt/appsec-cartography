"""Secret and config metadata. Values are never requested from the Nais API."""

import logging
from typing import Any

import neo4j

from cartography.client.core.tx import load
from cartography.graph.job import GraphJob
from cartography_nais.client import NaisGraphQLClient
from cartography_nais.models.configuration import NaisConfigSchema
from cartography_nais.models.configuration import NaisSecretSchema
from cartography.util import timeit

logger = logging.getLogger(__name__)

_COMMON_FIELDS = """
  id
  name
  lastModifiedAt
  lastModifiedBy { id }
  teamEnvironment { id environment { name } }
  workloads(first: 50) {
    pageInfo { hasNextPage endCursor }
    nodes { id }
  }
"""

SECRET_FRAGMENT = f"""
fragment SecretFields on Secret {{
  {_COMMON_FIELDS}
  keys
}}
"""

CONFIG_FRAGMENT = f"""
fragment ConfigFields on Config {{
  {_COMMON_FIELDS}
  values {{ name }}
}}
"""

CONFIGURATION_QUERY = (
    """
query GetTeamConfiguration($first: Int!, $cursor: Cursor) {
  teams(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      slug
      secrets(first: 100) {
        pageInfo { hasNextPage endCursor }
        nodes { ...SecretFields }
      }
      configs(first: 100) {
        pageInfo { hasNextPage endCursor }
        nodes { ...ConfigFields }
      }
    }
  }
}
"""
    + SECRET_FRAGMENT
    + CONFIG_FRAGMENT
)

_KINDS = (
    ("secrets", "Secret", "...SecretFields", SECRET_FRAGMENT),
    ("configs", "Config", "...ConfigFields", CONFIG_FRAGMENT),
)


def get(client: NaisGraphQLClient) -> list[dict[str, Any]]:
    teams = client.paginate(CONFIGURATION_QUERY, ["teams"], page_size=20)
    for team in teams:
        for field, node_type, selection, fragment in _KINDS:
            items = client.complete_connection(
                team.get(field),
                node_id=team["id"],
                node_type="Team",
                field=field,
                selection=selection,
                fragments=fragment,
            )
            for item in items:
                item["workloads"] = client.complete_connection(
                    item.get("workloads"),
                    node_id=item["id"],
                    node_type=node_type,
                    field="workloads",
                    selection="id",
                )
            team[field] = items
    return teams


def _transform_item(item: dict, team_slug: str, keys: list[str]) -> dict:
    team_env = item.get("teamEnvironment") or {}
    return {
        "id": item["id"],
        "name": item["name"],
        "team_slug": team_slug,
        "environment": (team_env.get("environment") or {}).get("name"),
        "team_environment_id": team_env.get("id"),
        "keys": sorted(keys),
        "last_modified_at": item.get("lastModifiedAt"),
        "last_modified_by_id": (item.get("lastModifiedBy") or {}).get("id"),
        "workload_ids": [w["id"] for w in item.get("workloads") or [] if w.get("id")],
    }


def transform(raw_teams: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """Return (secrets, configs)."""
    secrets = []
    configs = []
    for team in raw_teams:
        for s in team.get("secrets") or []:
            secrets.append(_transform_item(s, team["slug"], s.get("keys") or []))
        for c in team.get("configs") or []:
            keys = [v["name"] for v in c.get("values") or [] if v.get("name")]
            configs.append(_transform_item(c, team["slug"], keys))
    return secrets, configs


@timeit
def sync(
    neo4j_session: neo4j.Session,
    client: NaisGraphQLClient,
    tenant_id: str,
    update_tag: int,
    common_job_parameters: dict[str, Any],
    _teams_raw: list[dict[str, Any]] | None = None,
) -> None:
    logger.info("Syncing NAIS secret and config metadata")
    raw = _teams_raw if _teams_raw is not None else get(client)
    secrets, configs = transform(raw)
    logger.info("NAIS configuration: %d secrets, %d configs", len(secrets), len(configs))
    for schema, items in ((NaisSecretSchema(), secrets), (NaisConfigSchema(), configs)):
        load(
            neo4j_session,
            schema,
            items,
            lastupdated=update_tag,
            NAIS_TENANT_ID=tenant_id,
        )
        GraphJob.from_node_schema(schema, common_job_parameters).run(neo4j_session)
    logger.info("NAIS configuration sync complete")

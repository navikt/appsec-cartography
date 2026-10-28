import logging
from typing import Any

import neo4j

from cartography.client.core.tx import load
from cartography.client.core.tx import run_write_query
from cartography.graph.job import GraphJob
from cartography_nais.client import NaisGraphQLClient
from cartography_nais.models.team import NaisMemberSchema
from cartography_nais.models.team import NaisTeamSchema
from cartography.util import timeit

logger = logging.getLogger(__name__)

TEAMS_QUERY = """
query GetTeams($first: Int!, $cursor: Cursor) {
  teams(first: $first, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id
      slug
      purpose
      slackChannel
      lastSuccessfulSync
      externalResources {
        entraIDGroup { groupID }
        gitHubTeam { slug }
        googleGroup { email }
      }
      members(first: 500) {
        nodes {
          role
          user {
            id
            email
            name
            externalID
          }
        }
      }
    }
  }
}
"""


def get(client: NaisGraphQLClient) -> list[dict[str, Any]]:
    return client.paginate(TEAMS_QUERY, ["teams"])


def transform(raw_teams: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """
    Returns (teams, members).

    Each member dict includes a `team_id` field so HAS_MEMBER relationships
    can be built after members are loaded.
    Each team dict includes a `member_ids` list for the one-to-many relationship.
    """
    teams = []
    members_by_id: dict[str, dict] = {}

    for team in raw_teams:
        ext = team.get("externalResources") or {}
        entra = ext.get("entraIDGroup") or {}
        gh = ext.get("gitHubTeam") or {}
        google = ext.get("googleGroup") or {}

        member_ids = []
        for membership in (team.get("members") or {}).get("nodes") or []:
            user = membership.get("user") or {}
            uid = user.get("id")
            if not uid:
                continue
            member_ids.append(uid)
            if uid not in members_by_id:
                members_by_id[uid] = {
                    "id": uid,
                    "email": user.get("email"),
                    "name": user.get("name"),
                    "external_id": user.get("externalID"),
                }

        teams.append(
            {
                "id": team["id"],
                "slug": team["slug"],
                "purpose": team.get("purpose"),
                "slack_channel": team.get("slackChannel"),
                "last_successful_sync": team.get("lastSuccessfulSync"),
                "entra_group_id": entra.get("groupID"),
                "github_team_slug": gh.get("slug"),
                "google_group_email": google.get("email"),
                "member_ids": member_ids,
            }
        )

    return teams, list(members_by_id.values())


@timeit
def load_teams(
    neo4j_session: neo4j.Session,
    teams: list[dict],
    tenant_id: str,
    update_tag: int,
) -> None:
    load(
        neo4j_session,
        NaisTeamSchema(),
        teams,
        lastupdated=update_tag,
        NAIS_TENANT_ID=tenant_id,
    )


@timeit
def load_members(
    neo4j_session: neo4j.Session,
    members: list[dict],
    tenant_id: str,
    update_tag: int,
) -> None:
    load(
        neo4j_session,
        NaisMemberSchema(),
        members,
        lastupdated=update_tag,
        NAIS_TENANT_ID=tenant_id,
    )


@timeit
def load_team_member_relationships(
    neo4j_session: neo4j.Session,
    teams: list[dict],
    update_tag: int,
) -> None:
    """Write HAS_MEMBER edges from each team to its members."""
    run_write_query(
        neo4j_session,
        """
        UNWIND $teams AS team
        MATCH (t:NaisTeam {id: team.id})
        UNWIND team.member_ids AS mid
        MATCH (m:NaisMember {id: mid})
        MERGE (t)-[r:HAS_MEMBER]->(m)
        ON CREATE SET r.firstseen = timestamp()
        SET r.lastupdated = $update_tag
        """,
        teams=teams,
        update_tag=update_tag,
    )


@timeit
def cleanup(
    neo4j_session: neo4j.Session,
    common_job_parameters: dict[str, Any],
) -> None:
    GraphJob.from_node_schema(NaisTeamSchema(), common_job_parameters).run(
        neo4j_session
    )
    GraphJob.from_node_schema(NaisMemberSchema(), common_job_parameters).run(
        neo4j_session
    )


@timeit
def sync(
    neo4j_session: neo4j.Session,
    client: NaisGraphQLClient,
    tenant_id: str,
    update_tag: int,
    common_job_parameters: dict[str, Any],
    _teams_raw: list[dict[str, Any]] | None = None,
) -> None:
    logger.info("Syncing NAIS teams and members")
    raw = _teams_raw if _teams_raw is not None else get(client)
    teams, members = transform(raw)
    logger.info(
        "NAIS teams: fetched %d teams, %d unique members", len(teams), len(members)
    )
    load_members(neo4j_session, members, tenant_id, update_tag)
    load_teams(neo4j_session, teams, tenant_id, update_tag)
    load_team_member_relationships(neo4j_session, teams, update_tag)
    cleanup(neo4j_session, common_job_parameters)
    logger.info("NAIS teams sync complete")

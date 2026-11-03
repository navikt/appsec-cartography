import logging
from typing import Any

import neo4j

from cartography.client.core.tx import load
from cartography.client.core.tx import load_matchlinks
from cartography.graph.job import GraphJob
from cartography.helpers import normalize_email_for_matching
from cartography_nais.client import NaisGraphQLClient
from cartography_nais.models.team import NaisMemberSchema
from cartography_nais.models.team import NaisTeamEnvironmentSchema
from cartography_nais.models.team import NaisTeamMembershipMatchLink
from cartography_nais.models.team import NaisTeamSchema
from cartography.util import timeit

logger = logging.getLogger(__name__)

MEMBER_SELECTION = "role user { id email name externalID isAdmin }"

TEAMS_QUERY = f"""
query GetTeams($first: Int!, $cursor: Cursor) {{
  teams(first: $first, after: $cursor) {{
    pageInfo {{ hasNextPage endCursor }}
    nodes {{
      id
      slug
      purpose
      slackChannel
      lastSuccessfulSync
      deletionInProgress
      externalResources {{
        entraIDGroup {{ groupID }}
        gitHubTeam {{ slug }}
        googleGroup {{ email }}
        googleArtifactRegistry {{ repository }}
      }}
      environments {{
        id
        gcpProjectID
        environment {{ name }}
      }}
      members(first: 100) {{
        pageInfo {{ hasNextPage endCursor }}
        nodes {{ {MEMBER_SELECTION} }}
      }}
    }}
  }}
}}
"""


def get(client: NaisGraphQLClient) -> list[dict[str, Any]]:
    teams = client.paginate(TEAMS_QUERY, ["teams"], page_size=50)
    for team in teams:
        team["members"] = client.complete_connection(
            team.get("members"),
            node_id=team["id"],
            node_type="Team",
            field="members",
            selection=MEMBER_SELECTION,
        )
    return teams


def transform(
    raw_teams: list[dict[str, Any]],
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Return (teams, team_environments, members, memberships)."""
    teams = []
    environments = []
    members_by_id: dict[str, dict] = {}
    memberships = []

    for team in raw_teams:
        ext = team.get("externalResources") or {}
        teams.append(
            {
                "id": team["id"],
                "slug": team["slug"],
                "purpose": team.get("purpose"),
                "slack_channel": team.get("slackChannel"),
                "last_successful_sync": team.get("lastSuccessfulSync"),
                "deletion_in_progress": team.get("deletionInProgress"),
                "entra_group_id": (ext.get("entraIDGroup") or {}).get("groupID"),
                "github_team_slug": (ext.get("gitHubTeam") or {}).get("slug"),
                "google_group_email": (ext.get("googleGroup") or {}).get("email"),
                "google_artifact_registry": (
                    ext.get("googleArtifactRegistry") or {}
                ).get("repository"),
            }
        )

        for env in team.get("environments") or []:
            environments.append(
                {
                    "id": env["id"],
                    "team_id": team["id"],
                    "team_slug": team["slug"],
                    "environment": (env.get("environment") or {}).get("name"),
                    "gcp_project_id": env.get("gcpProjectID"),
                }
            )

        for membership in team.get("members") or []:
            user = membership.get("user") or {}
            uid = user.get("id")
            if not uid:
                continue
            memberships.append(
                {"team_id": team["id"], "member_id": uid, "role": membership["role"]}
            )
            members_by_id.setdefault(
                uid,
                {
                    "id": uid,
                    "email": user.get("email"),
                    "normalized_email": normalize_email_for_matching(user.get("email")),
                    "name": user.get("name"),
                    "external_id": user.get("externalID"),
                    "is_admin": user.get("isAdmin"),
                },
            )

    return teams, environments, list(members_by_id.values()), memberships


@timeit
def load_teams(
    neo4j_session: neo4j.Session,
    teams: list[dict],
    environments: list[dict],
    members: list[dict],
    memberships: list[dict],
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
    load(
        neo4j_session,
        NaisTeamEnvironmentSchema(),
        environments,
        lastupdated=update_tag,
        NAIS_TENANT_ID=tenant_id,
    )
    load(
        neo4j_session,
        NaisMemberSchema(),
        members,
        lastupdated=update_tag,
        NAIS_TENANT_ID=tenant_id,
    )
    load_matchlinks(
        neo4j_session,
        NaisTeamMembershipMatchLink(),
        memberships,
        lastupdated=update_tag,
        _sub_resource_label="NaisTenant",
        _sub_resource_id=tenant_id,
    )


@timeit
def cleanup(
    neo4j_session: neo4j.Session,
    common_job_parameters: dict[str, Any],
) -> None:
    GraphJob.from_matchlink(
        NaisTeamMembershipMatchLink(),
        "NaisTenant",
        common_job_parameters["NAIS_TENANT_ID"],
        common_job_parameters["UPDATE_TAG"],
    ).run(neo4j_session)
    for schema in (NaisTeamEnvironmentSchema(), NaisMemberSchema(), NaisTeamSchema()):
        GraphJob.from_node_schema(schema, common_job_parameters).run(neo4j_session)


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
    teams, environments, members, memberships = transform(raw)
    logger.info(
        "NAIS teams: %d teams, %d team environments, %d members, %d memberships",
        len(teams),
        len(environments),
        len(members),
        len(memberships),
    )
    load_teams(
        neo4j_session,
        teams,
        environments,
        members,
        memberships,
        tenant_id,
        update_tag,
    )
    cleanup(neo4j_session, common_job_parameters)
    logger.info("NAIS teams sync complete")

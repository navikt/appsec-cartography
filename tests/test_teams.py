from unittest.mock import MagicMock

import cartography_nais.teams
import tests.data.teams
from tests.util import check_nodes
from tests.util import check_rels

TEST_UPDATE_TAG = 123456789
TEST_TENANT_ID = "https://console.nav.cloud.nais.io/query"
COMMON_JOB_PARAMETERS = {
    "UPDATE_TAG": TEST_UPDATE_TAG,
    "TENANT_ID": TEST_TENANT_ID,
    "NAIS_TENANT_ID": TEST_TENANT_ID,
}


def test_transform_teams():
    teams, members = cartography_nais.teams.transform(tests.data.teams.MOCK_TEAMS_RAW)
    assert len(teams) == 2

    alpha = next(t for t in teams if t["slug"] == "team-alpha")
    assert alpha["entra_group_id"] == "entra-group-aaa"
    assert alpha["github_team_slug"] == "team-alpha"
    assert set(alpha["member_ids"]) == {"user-1", "user-2"}

    beta = next(t for t in teams if t["slug"] == "team-beta")
    assert beta["entra_group_id"] is None

    # Bob appears in both teams — deduplication ensures one member record
    assert len(members) == 2
    emails = {m["email"] for m in members}
    assert emails == {"alice@nav.no", "bob@nav.no"}


def test_load_nais_teams(neo4j_session):
    """Teams and members are loaded and relationships are created."""
    client = MagicMock()

    cartography_nais.teams.sync(
        neo4j_session,
        client,
        TEST_TENANT_ID,
        TEST_UPDATE_TAG,
        COMMON_JOB_PARAMETERS,
        _teams_raw=tests.data.teams.MOCK_TEAMS_RAW,
    )

    # Teams exist
    expected_teams = {("team-1", "team-alpha"), ("team-2", "team-beta")}
    assert check_nodes(neo4j_session, "NaisTeam", ["id", "slug"]) == expected_teams

    # Members exist and carry the UserAccount label
    expected_members = {
        ("user-1", "alice@nav.no"),
        ("user-2", "bob@nav.no"),
    }
    assert check_nodes(neo4j_session, "NaisMember", ["id", "email"]) == expected_members

    # HAS_MEMBER relationships exist
    expected_rels = {
        ("team-1", "user-1"),
        ("team-1", "user-2"),
        ("team-2", "user-2"),
    }
    assert (
        check_rels(
            neo4j_session,
            "NaisTeam",
            "id",
            "NaisMember",
            "id",
            "HAS_MEMBER",
            rel_direction_right=True,
        )
        == expected_rels
    )

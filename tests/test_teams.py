import copy
from unittest.mock import MagicMock

import cartography_nais.teams
import tests.data.teams
from tests.util import check_nodes
from tests.util import check_rels

TEST_UPDATE_TAG = 123456789
TEST_TENANT_ID = "https://console.nav.cloud.nais.io/query"


def _params(update_tag: int) -> dict:
    return {
        "UPDATE_TAG": update_tag,
        "TENANT_ID": TEST_TENANT_ID,
        "NAIS_TENANT_ID": TEST_TENANT_ID,
    }


def _sync(neo4j_session, raw, update_tag=TEST_UPDATE_TAG):
    cartography_nais.teams.sync(
        neo4j_session,
        MagicMock(),
        TEST_TENANT_ID,
        update_tag,
        _params(update_tag),
        _teams_raw=raw,
    )


def test_transform_teams():
    teams, environments, members, memberships = cartography_nais.teams.transform(
        tests.data.teams.MOCK_TEAMS_RAW
    )
    alpha = next(t for t in teams if t["slug"] == "team-alpha")
    assert alpha["entra_group_id"] == "entra-group-aaa"
    assert alpha["github_team_slug"] == "team-alpha"
    assert {(e["environment"], e["gcp_project_id"]) for e in environments} == {
        ("prod-gcp", "team-alpha-prod-1234"),
        ("prod-fss", None),
    }
    # Bob is in both teams but is one member.
    assert {m["normalized_email"] for m in members} == {"alice@nav.no", "bob@nav.no"}
    assert {(m["team_id"], m["member_id"], m["role"]) for m in memberships} == {
        ("team-1", "user-1", "OWNER"),
        ("team-1", "user-2", "MEMBER"),
        ("team-2", "user-2", "MEMBER"),
    }


def test_load_teams_links_environments_to_cluster_scoped_namespaces(neo4j_session):
    # The same namespace name exists in several clusters; only matching clusters link.
    neo4j_session.run(
        """
        UNWIND [
            {id: 'ns-gcp', cluster: 'prod-gcp'},
            {id: 'ns-fss', cluster: 'prod-fss'},
            {id: 'ns-dev', cluster: 'dev-gcp'}
        ] AS ns
        CREATE (:KubernetesNamespace {id: ns.id, name: 'team-alpha', cluster_name: ns.cluster})
        CREATE (:GCPProject {id: 'team-alpha-prod-1234'})
        """
    )
    _sync(neo4j_session, tests.data.teams.MOCK_TEAMS_RAW)

    assert check_rels(
        neo4j_session,
        "NaisTeam",
        "slug",
        "NaisTeamEnvironment",
        "environment",
        "HAS_ENVIRONMENT",
    ) == {("team-alpha", "prod-gcp"), ("team-alpha", "prod-fss")}
    assert check_rels(
        neo4j_session,
        "NaisTeamEnvironment",
        "environment",
        "KubernetesNamespace",
        "id",
        "HAS_NAMESPACE",
    ) == {("prod-gcp", "ns-gcp"), ("prod-fss", "ns-fss")}
    assert check_rels(
        neo4j_session,
        "NaisTeamEnvironment",
        "environment",
        "GCPProject",
        "id",
        "HAS_GCP_PROJECT",
    ) == {("prod-gcp", "team-alpha-prod-1234")}


def test_memberships_carry_role_and_stale_memberships_are_removed(neo4j_session):
    _sync(neo4j_session, tests.data.teams.MOCK_TEAMS_RAW)
    roles = {
        (r["team"], r["member"], r["role"])
        for r in neo4j_session.run(
            "MATCH (t:NaisTeam)-[r:HAS_MEMBER]->(m:NaisMember) "
            "RETURN t.id AS team, m.id AS member, r.role AS role"
        )
    }
    assert roles == {
        ("team-1", "user-1", "OWNER"),
        ("team-1", "user-2", "MEMBER"),
        ("team-2", "user-2", "MEMBER"),
    }
    assert check_nodes(neo4j_session, "UserAccount", ["id"]) == {("user-1",), ("user-2",)}

    # Bob leaves team-alpha but remains in team-beta.
    raw = copy.deepcopy(tests.data.teams.MOCK_TEAMS_RAW)
    raw[0]["members"] = raw[0]["members"][:1]
    _sync(neo4j_session, raw, TEST_UPDATE_TAG + 1)

    assert check_rels(
        neo4j_session, "NaisTeam", "id", "NaisMember", "id", "HAS_MEMBER"
    ) == {("team-1", "user-1"), ("team-2", "user-2")}

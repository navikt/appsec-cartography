import re
from unittest.mock import MagicMock

import cartography_nais.configuration
import cartography_nais.teams
import cartography_nais.workloads
import tests.data.configuration
import tests.data.teams
import tests.data.workloads
from tests.util import check_rels

TEST_UPDATE_TAG = 123456789
TEST_TENANT_ID = "https://console.nav.cloud.nais.io/query"
COMMON_JOB_PARAMETERS = {
    "UPDATE_TAG": TEST_UPDATE_TAG,
    "TENANT_ID": TEST_TENANT_ID,
    "NAIS_TENANT_ID": TEST_TENANT_ID,
}


def test_queries_never_request_values():
    query = cartography_nais.configuration.CONFIGURATION_QUERY
    assert "viewSecretValues" not in query
    assert not re.search(r"\bvalue\b", query)
    assert "values { name }" in query


def test_transform_keeps_only_key_names():
    secrets, configs = cartography_nais.configuration.transform(
        tests.data.configuration.MOCK_CONFIGURATION_RAW
    )
    assert secrets[0]["keys"] == ["API_KEY", "PASSWORD"]
    assert secrets[0]["workload_ids"] == ["app-1", "job-1"]
    assert configs[0]["keys"] == ["FEATURE_X", "LOG_LEVEL"]
    assert configs[0]["last_modified_by_id"] is None


def test_load_configuration_links_environment_workloads_and_modifier(neo4j_session):
    client = MagicMock()
    args = (neo4j_session, client, TEST_TENANT_ID, TEST_UPDATE_TAG, COMMON_JOB_PARAMETERS)
    cartography_nais.teams.sync(*args, _teams_raw=tests.data.teams.MOCK_TEAMS_RAW)
    cartography_nais.workloads.sync(
        *args, _workloads_raw=tests.data.workloads.MOCK_WORKLOADS_RAW
    )
    cartography_nais.configuration.sync(
        *args, _teams_raw=tests.data.configuration.MOCK_CONFIGURATION_RAW
    )

    assert check_rels(
        neo4j_session, "NaisTeamEnvironment", "id", "NaisSecret", "id", "HAS_SECRET"
    ) == {("teamenv-alpha-prod-gcp", "secret-1")}
    assert check_rels(
        neo4j_session, "NaisApp", "id", "NaisSecret", "id", "USES_SECRET"
    ) == {("app-1", "secret-1"), ("job-1", "secret-1")}
    assert check_rels(
        neo4j_session, "NaisApp", "id", "NaisConfig", "id", "USES_CONFIG"
    ) == {("app-1", "config-1")}
    assert check_rels(
        neo4j_session, "NaisSecret", "id", "NaisMember", "id", "LAST_MODIFIED_BY"
    ) == {("secret-1", "user-1")}

from unittest.mock import Mock

import pytest
from cartography.config import Config

import cartography_nais
from tests.data.teams import MOCK_TEAMS_RAW
from tests.data.workloads import MOCK_WORKLOADS_RAW
from tests.util import check_nodes


def test_extracted_collector_runs_with_upstream_and_packaged_queries(
    neo4j_session, monkeypatch, tmp_path
):
    token_file = tmp_path / "token"
    token_file.write_text("test-token")
    monkeypatch.setattr(cartography_nais.teams, "get", lambda client: MOCK_TEAMS_RAW)
    monkeypatch.setattr(
        cartography_nais.workloads,
        "get_workloads",
        lambda client, deployment_limit: MOCK_WORKLOADS_RAW,
    )
    cartography_nais.start_nais_ingestion(
        neo4j_session,
        Config(neo4j_uri="bolt://unused", update_tag=123),
        base_url="https://nais.example/graphql",
        token_path=str(token_file),
    )
    assert len(check_nodes(neo4j_session, "NaisTeam", ["id"])) == 2
    assert len(check_nodes(neo4j_session, "NaisApp", ["id"])) == 3
    assert len(check_nodes(neo4j_session, "NaisDeployment", ["id"])) == 4


def test_invalid_token_fails_before_writing_graph_data(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("")
    session = Mock()
    with pytest.raises(ValueError, match="token file is empty"):
        cartography_nais.start_nais_ingestion(
            session,
            Config(neo4j_uri="bolt://unused", update_tag=123),
            base_url="https://nais.example/graphql",
            token_path=str(token_file),
        )
    session.run.assert_not_called()

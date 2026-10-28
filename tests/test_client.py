from unittest.mock import Mock

import pytest

from cartography_nais.client import NaisGraphQLClient
from cartography_nais.workloads import get_environments


def test_client_refreshes_token_without_logging_it(tmp_path, caplog):
    token_file = tmp_path / "token"
    token_file.write_text("test-first-token")
    client = NaisGraphQLClient(str(token_file), "https://nais.example/graphql")
    client._session.post = Mock()
    client._session.post.return_value.json.return_value = {"data": {"teams": {}}}

    with caplog.at_level("DEBUG"):
        client.query("query { teams { nodes { id } } }")
        token_file.write_text("test-second-token")
        client.query("query { teams { nodes { id } } }")
    calls = client._session.post.call_args_list
    assert calls[0].kwargs["headers"]["Authorization"].endswith("test-first-token")
    assert calls[1].kwargs["headers"]["Authorization"].endswith("test-second-token")
    assert "test-first-token" not in caplog.text
    assert "test-second-token" not in caplog.text


@pytest.mark.parametrize(
    "response",
    [
        {"errors": [{"message": "unauthorized"}], "data": {"teams": None}},
        {"data": None},
        {"data": {"teams": None}},
        {"data": {"teams": {"nodes": [], "pageInfo": None}}},
    ],
)
def test_invalid_responses_abort_instead_of_returning_partial_data(tmp_path, response):
    token_file = tmp_path / "token"
    token_file.write_text("test-token")
    client = NaisGraphQLClient(str(token_file), "https://nais.example/graphql")
    client._session.post = Mock()
    client._session.post.return_value.json.return_value = response
    with pytest.raises(RuntimeError):
        client.paginate("query", ["teams"])


def test_pagination_collects_all_pages(tmp_path):
    token_file = tmp_path / "token"
    token_file.write_text("test-token")
    client = NaisGraphQLClient(str(token_file), "https://nais.example/graphql")
    client._session.post = Mock()
    client._session.post.return_value.json.side_effect = [
        {
            "data": {
                "teams": {
                    "nodes": [{"id": "first"}],
                    "pageInfo": {"hasNextPage": True, "endCursor": "next"},
                }
            }
        },
        {
            "data": {
                "teams": {
                    "nodes": [{"id": "second"}],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        },
    ]
    assert client.paginate("query", ["teams"]) == [{"id": "first"}, {"id": "second"}]


@pytest.mark.parametrize("data", [{}, {"environments": None}, {"environments": {}}])
def test_missing_environment_data_cannot_trigger_empty_workload_cleanup(data):
    client = Mock()
    client.query.return_value = data
    with pytest.raises((KeyError, TypeError)):
        get_environments(client)

from unittest.mock import Mock

import pytest

from cartography_nais import cli


def test_runner_uses_upstream_sync_and_propagates_exit_status(monkeypatch):
    monkeypatch.setenv("NEO4J_PASSWORD", "test-password")
    monkeypatch.setenv("NAIS_BASE_URL", "https://nais.example/graphql")
    monkeypatch.setenv("NAIS_SERVICE_ACCOUNT_TOKEN_PATH", "/test/token")
    ingestion = Mock()
    monkeypatch.setattr(cli, "start_nais_ingestion", ingestion)

    def run(sync, config):
        assert config.neo4j_uri == "bolt://localhost:7687"
        assert config.neo4j_user == "neo4j"
        assert config.neo4j_password == "test-password"
        config.update_tag = 123
        sync._stages["nais"]("session", config)
        ingestion.assert_called_once_with(
            "session",
            config,
            base_url="https://nais.example/graphql",
            token_path="/test/token",
        )
        return 1

    monkeypatch.setattr(cli, "run_with_config", run)
    assert cli.main(["--neo4j-uri", "bolt://localhost:7687"]) == 1


def test_runner_rejects_missing_configuration(monkeypatch, capsys):
    monkeypatch.delenv("NAIS_BASE_URL", raising=False)
    monkeypatch.delenv("NAIS_SERVICE_ACCOUNT_TOKEN_PATH", raising=False)
    with pytest.raises(SystemExit) as exc:
        cli.main(["--neo4j-uri", "bolt://localhost:7687"])
    assert exc.value.code == 2
    assert "Nais base URL and token path must be configured" in capsys.readouterr().err

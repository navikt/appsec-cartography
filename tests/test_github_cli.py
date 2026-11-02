from unittest.mock import Mock

import pytest

from cartography_github import cli


def test_runner_configures_local_incremental_parallel_stage(monkeypatch):
    monkeypatch.setenv("NEO4J_PASSWORD", "test-password")
    monkeypatch.setenv("GITHUB_CONFIG", "encoded")
    ingestion = Mock()
    monkeypatch.setattr(cli, "start_github_ingestion", ingestion)

    def run(sync, config):
        assert list(sync._stages) == ["create-indexes", "github"]
        assert config.github_config == "encoded"
        assert config.github_commit_lookback_days == 14
        sync._stages["github"]("session", config)
        ingestion.assert_called_once_with(
            "session", config, parallel_workers=4, incremental_sync=True
        )
        return 1

    monkeypatch.setattr(cli, "run_with_config", run)
    assert cli.main(
        [
            "--neo4j-uri", "bolt://localhost:7687",
            "--github-commit-lookback-days", "14",
        ]
    ) == 1


def test_runner_can_force_a_full_refresh_and_change_worker_count(monkeypatch):
    monkeypatch.setenv("NEO4J_PASSWORD", "test-password")
    monkeypatch.setenv("GITHUB_CONFIG", "encoded")
    ingestion = Mock()
    monkeypatch.setattr(cli, "start_github_ingestion", ingestion)

    def run(sync, config):
        sync._stages["github"]("session", config)
        ingestion.assert_called_once_with(
            "session", config, parallel_workers=2, incremental_sync=False
        )
        return 0

    monkeypatch.setattr(cli, "run_with_config", run)
    assert cli.main(
        [
            "--neo4j-uri", "bolt://localhost:7687",
            "--github-parallel-workers", "2",
            "--no-github-incremental-sync",
        ]
    ) == 0


def test_runner_rejects_nonpositive_workers(monkeypatch, capsys):
    monkeypatch.setenv("NEO4J_PASSWORD", "test-password")
    monkeypatch.setenv("GITHUB_CONFIG", "encoded")
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "--neo4j-uri", "bolt://localhost:7687",
                "--github-parallel-workers", "0",
            ]
        )
    assert exc.value.code == 2
    assert "--github-parallel-workers must be at least 1" in capsys.readouterr().err

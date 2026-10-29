from datetime import datetime
from datetime import timedelta
from datetime import timezone
from unittest.mock import Mock

import cartography.intel.github.actions as gh_actions
import cartography.intel.github.codeowners as gh_codeowners
import cartography.intel.github.repos as gh_repos
import cartography.intel.github.util as gh_util
from cartography_github import cli
from cartography_github.cache import CacheEntry
from cartography_github.cache import Neo4jFetchCache
from cartography_github.fetchers import CachedGitHubFetches
from cartography_github.metadata import RepoState
from cartography_github.metadata import transform_repo_states

NOW = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
OLD_PUSH = NOW - timedelta(days=60)
GRAPHQL_URL = "https://api.github.com/graphql"
DOTCOM = "https://api.github.com"
GHES_GRAPHQL_URL = "https://github.example.com/api/graphql"
GHES = "https://github.example.com/api/v3"


class FakeCache:
    def __init__(self):
        self.entries = {}

    def get(self, key, fingerprint):
        stored = self.entries.get(key)
        if stored is None or stored[0] != fingerprint:
            return None
        return stored[1]

    def put(self, key, fingerprint, oid, payload, fetched_at):
        self.entries[key] = (fingerprint, CacheEntry(payload, oid, fetched_at))
        return True


class Clock:
    def __init__(self, now=NOW):
        self.now = now.timestamp()

    def __call__(self):
        return self.now


def make_fetches(state=None, clock=None):
    state = state or RepoState("oid-1", "main", OLD_PUSH)
    return CachedGitHubFetches(
        FakeCache(),
        {(DOTCOM, "navikt", "app"): state},
        clock=clock or Clock(),
    )


def test_installed_routes_upstream_file_reads_through_pinned_cache_and_restores():
    fetches = make_fetches()
    fetches._get_file_content = Mock(return_value="on: push")

    with fetches.installed():
        for _ in range(2):
            content = gh_actions.get_workflow_content(
                "token", GRAPHQL_URL, "NAVIKT", "app", ".github/workflows/ci.yml"
            )
            assert content == "on: push"

    fetches._get_file_content.assert_called_once_with(
        "token",
        "NAVIKT",
        "app",
        ".github/workflows/ci.yml",
        ref="oid-1",
        base_url="https://api.github.com",
    )
    assert fetches.stats == {"file_content.miss": 1, "file_content.hit": 1}
    for module in (gh_actions, gh_codeowners, gh_repos):
        assert module.get_file_content is gh_util.get_file_content


def test_file_content_is_refetched_when_default_branch_moves_or_entry_expires():
    clock = Clock()
    fetches = make_fetches(clock=clock)
    fetches._get_file_content = Mock(return_value=None)

    fetches.get_file_content("token", "navikt", "app", "uv.lock")
    fetches.get_file_content("token", "navikt", "app", "uv.lock")
    fetches._repo_states[(DOTCOM, "navikt", "app")] = RepoState(
        "oid-2", "main", OLD_PUSH
    )
    fetches.get_file_content("token", "navikt", "app", "uv.lock")
    clock.now += timedelta(days=7).total_seconds()
    fetches.get_file_content("token", "navikt", "app", "uv.lock")

    assert fetches.stats == {"file_content.miss": 3, "file_content.hit": 1}


def test_file_content_bypasses_unknown_repos_and_other_refs():
    fetches = make_fetches()
    fetches._get_file_content = Mock(return_value="content")

    fetches.get_file_content("token", "navikt", "app", "CODEOWNERS", ref="feature")
    fetches.get_file_content("token", "navikt", "unknown", "CODEOWNERS")

    assert fetches.stats == {"file_content.bypass": 2}
    assert fetches._get_file_content.call_args.kwargs["ref"] == "HEAD"


def test_dep_manifests_are_cached_only_when_complete_and_settled():
    clock = Clock()
    fetches = make_fetches(
        state=RepoState("oid-1", "main", NOW - timedelta(hours=1)),
        clock=clock,
    )
    manifests = [{"blobPath": "/navikt/app/blob/main/uv.lock", "dependencies": {}}]
    fetches._get_repo_dep_manifests = Mock(return_value=(manifests, True))

    fetches.get_repo_dep_manifests("token", GRAPHQL_URL, "navikt", "app")
    clock.now += timedelta(hours=6).total_seconds()
    fetches._get_repo_dep_manifests.return_value = (manifests[:0], False)
    fetches.get_repo_dep_manifests("token", GRAPHQL_URL, "navikt", "app")
    fetches._get_repo_dep_manifests.return_value = (manifests, True)
    fetches.get_repo_dep_manifests("token", GRAPHQL_URL, "navikt", "app")

    assert fetches.get_repo_dep_manifests("token", GRAPHQL_URL, "navikt", "app") == (
        manifests,
        True,
    )
    assert fetches._get_repo_dep_manifests.call_count == 3
    assert fetches.stats == {
        "dep_manifests.miss": 3,
        "dep_manifests.not_cached": 2,
        "dep_manifests.hit": 1,
    }


def test_dep_manifests_are_refetched_after_default_branch_rename_at_same_commit():
    fetches = make_fetches(state=RepoState("oid-1", "master", OLD_PUSH))
    fetches._get_repo_dep_manifests = Mock(
        side_effect=[
            ([{"blobPath": "/navikt/app/blob/master/uv.lock"}], True),
            ([{"blobPath": "/navikt/app/blob/main/uv.lock"}], True),
        ]
    )

    fetches.get_repo_dep_manifests("token", GRAPHQL_URL, "navikt", "app")
    fetches._repo_states[(DOTCOM, "navikt", "app")] = RepoState(
        "oid-1", "main", OLD_PUSH
    )
    manifests, _ = fetches.get_repo_dep_manifests("token", GRAPHQL_URL, "navikt", "app")

    assert manifests == [{"blobPath": "/navikt/app/blob/main/uv.lock"}]
    assert fetches.stats == {"dep_manifests.miss": 2}


def test_same_repo_name_on_another_github_instance_does_not_share_state_or_cache():
    fetches = make_fetches()
    fetches._repo_states[(GHES, "navikt", "app")] = RepoState(
        "oid-ghes", "main", OLD_PUSH
    )
    fetches._get_file_content = Mock(return_value="content")
    fetches._get_repo_commits = Mock(return_value=[])
    since = NOW - timedelta(days=30)

    fetches.get_file_content("token", "navikt", "app", "CODEOWNERS", base_url=DOTCOM)
    fetches.get_file_content("token", "navikt", "app", "CODEOWNERS", base_url=GHES)
    fetches.get_repo_commits("token", GHES_GRAPHQL_URL, "navikt", "unknown", since)

    assert [c.kwargs["ref"] for c in fetches._get_file_content.call_args_list] == [
        "oid-1",
        "oid-ghes",
    ]
    assert fetches.stats == {"file_content.miss": 2, "commits.fetched": 1}


def test_commits_are_skipped_only_without_a_push_in_the_lookback_window():
    fetches = make_fetches()
    fetches._repo_states[(DOTCOM, "navikt", "active")] = RepoState("oid", "main", NOW)
    fetches._get_repo_commits = Mock(return_value=[{"committedDate": "x"}])
    since = NOW - timedelta(days=30)

    assert fetches.get_repo_commits("token", GRAPHQL_URL, "navikt", "app", since) == []
    assert fetches.get_repo_commits("token", GRAPHQL_URL, "navikt", "active", since)
    assert fetches.get_repo_commits("token", GRAPHQL_URL, "navikt", "new", since)
    assert fetches._get_repo_commits.call_count == 2


def test_repo_states_skip_repos_without_a_default_branch():
    states = transform_repo_states(
        DOTCOM,
        "NAVIKT",
        [
            None,
            {"name": "Empty", "pushedAt": None, "defaultBranchRef": None},
            {
                "name": "App",
                "pushedAt": "2026-10-01T10:00:00Z",
                "defaultBranchRef": {"name": "main", "target": {"oid": "abc"}},
            },
        ],
    )

    assert states == {
        (DOTCOM, "navikt", "app"): RepoState(
            "abc", "main", datetime(2026, 10, 1, 10, tzinfo=timezone.utc)
        ),
    }


def test_neo4j_cache_round_trip_fingerprint_and_prune(neo4j_session):
    cache = Neo4jFetchCache(neo4j_session)
    cache.ensure_index()
    cache.put("file:navikt/app:uv.lock", "fp", "oid", {"content": "æ"}, 100.0)

    assert cache.get("file:navikt/app:uv.lock", "fp") == CacheEntry(
        {"content": "æ"}, "oid", 100.0
    )
    assert cache.get("file:navikt/app:uv.lock", "other") is None
    assert cache.prune(10, now=105.0) == 0
    assert cache.prune(10, now=111.0) == 1
    assert cache.get("file:navikt/app:uv.lock", "fp") is None


def test_runner_uses_upstream_sync_with_cached_github_stage(monkeypatch):
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
            "session",
            config,
            use_cache=False,
            max_age=timedelta(days=7),
            manifest_settle=timedelta(hours=6),
        )
        return 1

    monkeypatch.setattr(cli, "run_with_config", run)
    assert (
        cli.main(
            [
                "--neo4j-uri",
                "bolt://localhost:7687",
                "--github-commit-lookback-days",
                "14",
                "--no-fetch-cache",
            ]
        )
        == 1
    )

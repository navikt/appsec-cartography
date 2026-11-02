import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import cartography_github as github
from cartography.config import Config


@pytest.fixture
def stages(monkeypatch):
    mocks = {}
    for module, name in (
        ("users", "get_organization"),
        ("organizations", "sync"),
        ("users", "sync"),
        ("users", "cleanup"),
        ("external_identities", "sync"),
        ("repos", "sync"),
        ("personal_access_tokens", "sync"),
        ("app_installations", "sync"),
        ("webhooks", "sync"),
        ("dependabot_alerts", "sync"),
        ("teams", "sync_github_teams"),
        ("codeowners", "sync"),
        ("actions", "sync"),
        ("commits", "sync_github_commits"),
        ("packages", "sync_packages"),
        ("container_images", "sync_container_images"),
        ("container_image_tags", "sync_container_image_tags"),
        ("container_image_attestations", "sync_container_image_attestations"),
        ("supply_chain", "sync"),
    ):
        mock = Mock()
        monkeypatch.setattr(getattr(github, module), name, mock)
        mocks[f"{module}.{name}"] = mock
    mocks["users.get_organization"].return_value = ([], [], {"url": "https://github.com/navikt"})
    mocks["repos.sync"].return_value = SimpleNamespace(
        repos=[{"id": "https://github.com/navikt/app", "fullname": "navikt/app"}],
        raw_repos=[{"name": "app", "isArchived": False, "isDisabled": False}],
        manifests=[],
        manifests_cleanup_safe=True,
        repos_complete=True,
        repo_pushedat_updates=[{"repo_url": "https://github.com/navikt/app", "pushedat": "2026-10-01T12:00:00Z"}],
        manifest_bookmark_updates=[{"repo_url": "https://github.com/navikt/app", "pushedat": "2026-10-01T12:00:00Z"}],
    )
    mocks["actions.sync"].return_value = SimpleNamespace(
        workflows=[{"id": "workflow"}], incomplete_repo_urls=[]
    )
    mocks["packages.sync_packages"].return_value = SimpleNamespace(
        cleanup_safe=False, packages=[]
    )
    mocks["bookmark"] = Mock()
    mocks["manifest_bookmark"] = Mock()
    mocks["cleanup"] = Mock()
    monkeypatch.setattr(github.repos, "_write_synced_pushedat", mocks["bookmark"])
    monkeypatch.setattr(github.repos, "_write_manifest_bookmarks", mocks["manifest_bookmark"])
    monkeypatch.setattr(github, "cleanup_unscoped_github_resources", mocks["cleanup"])
    return mocks


def config():
    encoded = base64.b64encode(json.dumps({
        "organization": [{"name": "navikt", "url": "https://api.github.com/graphql", "token": "test-token"}]
    }).encode()).decode()
    return Config(
        neo4j_uri="bolt://localhost:7687", github_config=encoded, update_tag=123
    )


def test_local_stages_preserve_upstream_scope_and_commit_bookmarks_last(stages):
    order = []
    stages["supply_chain.sync"].side_effect = lambda *a, **k: order.append("supply-chain")
    stages["cleanup"].side_effect = lambda *a, **k: order.append("cleanup")
    stages["bookmark"].side_effect = lambda *a, **k: order.append("bookmark")
    stages["manifest_bookmark"].side_effect = lambda *a, **k: order.append("manifest-bookmark")

    github.start_github_ingestion(Mock(), config(), parallel_workers=4, incremental_sync=True)

    assert stages["repos.sync"].call_args.kwargs == {
        "parallel_workers": 4, "incremental_sync": True,
    }
    assert stages["actions.sync"].call_args.kwargs == {
        "parallel_workers": 4, "skip_archived_repos": True, "skip_unchanged_repos": True,
    }
    assert stages["commits.sync_github_commits"].call_args.kwargs == {"skip_stale_repos": True}
    for name in (
        "organizations.sync", "external_identities.sync", "app_installations.sync",
        "webhooks.sync", "codeowners.sync", "dependabot_alerts.sync",
    ):
        stages[name].assert_called_once()
    stages["container_images.sync_container_images"].assert_not_called()
    assert stages["webhooks.sync"].call_args.kwargs == {"repos_complete": True}
    assert stages["supply_chain.sync"].call_args.kwargs["workflows"] == [{"id": "workflow"}]
    assert order == ["supply-chain", "cleanup", "manifest-bookmark", "bookmark"]


def test_failed_stage_does_not_advance_incremental_bookmarks_or_run_global_cleanup(stages):
    stages["supply_chain.sync"].side_effect = RuntimeError("sync failed")

    with pytest.raises(RuntimeError, match="sync failed"):
        github.start_github_ingestion(Mock(), config())

    stages["bookmark"].assert_not_called()
    stages["manifest_bookmark"].assert_not_called()
    stages["cleanup"].assert_not_called()


def test_failed_global_cleanup_does_not_advance_incremental_bookmarks(stages):
    stages["cleanup"].side_effect = RuntimeError("cleanup failed")

    with pytest.raises(RuntimeError, match="cleanup failed"):
        github.start_github_ingestion(Mock(), config())

    stages["bookmark"].assert_not_called()
    stages["manifest_bookmark"].assert_not_called()


def test_incomplete_listing_skips_global_repo_cleanup_and_bookmarks(stages):
    stages["repos.sync"].return_value.repos_complete = False

    github.start_github_ingestion(Mock(), config())

    assert stages["webhooks.sync"].call_args.kwargs == {"repos_complete": False}
    stages["bookmark"].assert_not_called()
    stages["cleanup"].assert_not_called()
    stages["users.cleanup"].assert_called_once()


def test_consumers_receive_transformed_or_raw_repositories(stages):
    github.start_github_ingestion(Mock(), config())

    result = stages["repos.sync"].return_value
    assert stages["webhooks.sync"].call_args.args[5] is result.repos
    assert stages["codeowners.sync"].call_args.args[5] is result.repos
    assert stages["supply_chain.sync"].call_args.args[6] is result.raw_repos


def test_unavailable_workflow_listing_holds_back_that_repos_bookmark(stages):
    other = {"repo_url": "https://github.com/navikt/other", "pushedat": "2026-10-02T00:00:00Z"}
    stages["repos.sync"].return_value.repo_pushedat_updates.append(other)
    stages["actions.sync"].return_value.incomplete_repo_urls.append(
        "https://github.com/navikt/app"
    )

    github.start_github_ingestion(Mock(), config())

    assert stages["bookmark"].call_args.args[1] == [other]


def test_archived_and_disabled_repositories_are_excluded_from_commit_collection(stages):
    stages["repos.sync"].return_value.raw_repos.extend(
        [
            {"name": "archived", "isArchived": True},
            {"name": "disabled", "isDisabled": True},
        ]
    )

    github.start_github_ingestion(Mock(), config())

    assert stages["commits.sync_github_commits"].call_args.args[4] == ["app"]


def test_full_refresh_does_not_write_incremental_bookmarks(stages):
    github.start_github_ingestion(Mock(), config(), incremental_sync=False)

    stages["bookmark"].assert_not_called()
    assert stages["actions.sync"].call_args.kwargs["skip_unchanged_repos"] is False


def test_empty_package_listing_still_cleans_up_ghcr_when_complete(stages):
    stages["packages.sync_packages"].return_value.cleanup_safe = True
    stages["container_images.sync_container_images"].return_value = ([], [], [], [])

    github.start_github_ingestion(Mock(), config())

    stages["container_images.sync_container_images"].assert_called_once()
    stages["container_image_tags.sync_container_image_tags"].assert_called_once()
    stages["container_image_attestations.sync_container_image_attestations"].assert_called_once()

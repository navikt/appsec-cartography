from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import cartography.intel.github.codeowners as upstream_codeowners
import cartography.intel.github.dependabot_alerts as upstream_dependabot
import cartography.intel.github.supply_chain as upstream_supply_chain
import cartography.intel.github.webhooks as upstream_webhooks


@pytest.mark.parametrize("exclude", [True, False])
def test_webhooks_skip_archived_requests_without_skipping_inactive_or_org_hooks(
    monkeypatch,
    exclude,
):
    from cartography_github import webhooks

    repos = [
        {
            "id": f"https://github.com/example/{name}",
            "url": f"https://github.com/example/{name}",
            "fullname": f"example/{name}",
        }
        for name in ("inactive", "archived")
    ]
    events = []
    monkeypatch.setattr(
        upstream_webhooks,
        "get_organization_webhooks",
        lambda *args: events.append("org") or [],
    )
    monkeypatch.setattr(
        upstream_webhooks,
        "get_repository_webhooks",
        lambda token, api, fullname: events.append(fullname) or [],
    )
    monkeypatch.setattr(upstream_webhooks, "load_webhooks", lambda *args: None)
    monkeypatch.setattr(
        upstream_webhooks, "cleanup", lambda *args: events.append("cleanup")
    )
    monkeypatch.setattr(
        webhooks,
        "touch_skipped_repo_resources",
        lambda *args, **kwargs: events.append(("preserve", args[1])),
    )
    excluded = {repos[1]["id"]} if exclude else set()

    webhooks.sync(
        Mock(),
        {"UPDATE_TAG": 99},
        "token",
        "https://api.github.com/graphql",
        "example",
        repos,
        excluded_repo_urls=excluded,
    )

    assert "org" in events
    assert "example/inactive" in events
    assert ("example/archived" in events) is not exclude
    assert events.index(("preserve", excluded)) < events.index("cleanup")


@pytest.mark.parametrize("exclude", [True, False])
def test_codeowners_retains_archive_rules_and_matches_while_refreshing_inactive_repos(
    monkeypatch,
    exclude,
):
    from cartography_github import codeowners

    repos = [
        {
            "id": f"https://github.com/example/{name}",
            "name": name,
            "owner_org_id": "https://github.com/example",
            "defaultbranch": "main",
        }
        for name in ("inactive", "archived")
    ]
    events = []
    monkeypatch.setattr(
        upstream_codeowners,
        "get_effective_codeowners_file",
        lambda token, api, repo_url, branch: (
            events.append(repo_url)
            or SimpleNamespace(cleanup_safe=True, content=None, source_path=None)
        ),
    )
    for name in ("load_codeowner_rules", "load_manifest_matches"):
        monkeypatch.setattr(upstream_codeowners, name, lambda *args: None)
    for name in ("cleanup_codeowner_rules", "cleanup_manifest_matches"):
        monkeypatch.setattr(
            upstream_codeowners,
            name,
            lambda *args, name=name: events.append(name),
        )
    monkeypatch.setattr(
        codeowners,
        "touch_skipped_repo_resources",
        lambda *args, **kwargs: events.append(("preserve", args[1], kwargs)),
        raising=False,
    )
    excluded = {repos[1]["id"]} if exclude else set()

    codeowners.sync(
        Mock(),
        {"UPDATE_TAG": 99},
        "token",
        "https://api.github.com/graphql",
        "example",
        repos,
        [],
        excluded_repo_urls=excluded,
    )

    assert repos[0]["id"] in events
    assert (repos[1]["id"] in events) is not exclude
    preservation = next(event for event in events if isinstance(event, tuple))
    assert preservation[1] == excluded
    assert preservation[2]["matchlinks"][0].rel_label == "MATCHES_CODEOWNER_RULE"
    assert events.index(preservation) < events.index("cleanup_manifest_matches")
    assert "cleanup_codeowner_rules" in events


@pytest.mark.parametrize("incremental", [True, False])
def test_dependabot_ingests_new_and_changed_alerts_on_inactive_repos(
    monkeypatch,
    incremental,
):
    from cartography_github import dependabot_alerts

    inactive_url = "https://github.com/example/inactive"
    archived_url = "https://github.com/example/archived"
    alerts = [
        {
            "html_url": f"{inactive_url}/security/dependabot/1",
            "state": "open",
            "repository": {"html_url": inactive_url},
        },
        {
            "html_url": f"{inactive_url}/security/dependabot/2",
            "state": "fixed",
            "repository": {"html_url": inactive_url},
        },
        {
            "html_url": f"{archived_url}/security/dependabot/1",
            "repository": {"html_url": archived_url},
        },
        {
            "html_url": "https://github.com/example/disabled/security/dependabot/1",
            "repository": {"disabled": True},
        },
    ]
    fetch = Mock(return_value=SimpleNamespace(cleanup_safe=True, alerts=alerts))
    monkeypatch.setattr(upstream_dependabot, "get", fetch)
    monkeypatch.setattr(upstream_dependabot, "load_users", lambda *args: None)
    loaded = []
    events = []
    monkeypatch.setattr(
        upstream_dependabot,
        "load_alerts",
        lambda session, rows, *args: loaded.extend(rows),
    )
    monkeypatch.setattr(
        upstream_dependabot, "cleanup", lambda *args: events.append("cleanup")
    )
    monkeypatch.setattr(
        dependabot_alerts,
        "touch_skipped_repo_resources",
        lambda *args, **kwargs: events.append(("preserve", args[1])),
        raising=False,
    )
    excluded = {archived_url} if incremental else None

    dependabot_alerts.sync(
        Mock(),
        {"UPDATE_TAG": 99},
        "token",
        "https://api.github.com/graphql",
        "example",
        excluded_repo_urls=excluded,
    )

    fetch.assert_called_once()
    assert [row["state"] for row in loaded[:2]] == ["open", "fixed"]
    assert len(loaded) == (2 if incremental else 4)
    assert events[-1] == "cleanup"
    if incremental:
        assert ("preserve", excluded) in events[:-1]


@pytest.mark.parametrize("exclude", [True, False])
def test_supply_chain_avoids_new_archive_matches_including_package_owner_fallback(
    monkeypatch,
    exclude,
):
    from cartography_github import supply_chain

    repos = [
        {"url": f"https://github.com/example/{name}", "name": name}
        for name in ("inactive", "archived")
    ]
    workflows = [
        {"repo_url": repo["url"], "path": ".github/workflows/build.yml"}
        for repo in repos
    ]
    events = []
    loaded = []
    downloaded = []
    monkeypatch.setattr(
        supply_chain,
        "run_write_query",
        lambda *args, **kwargs: events.append(("preserve", kwargs["repo_urls"])),
        raising=False,
    )
    monkeypatch.setattr(
        upstream_supply_chain,
        "get_unmatched_container_images_with_history",
        lambda *args, **kwargs: [object()],
    )
    for name in (
        "get_unmatched_gcp_images_with_history",
        "get_unmatched_scaleway_images_with_history",
    ):
        monkeypatch.setattr(upstream_supply_chain, name, lambda *args, **kwargs: [])
    monkeypatch.setattr(
        upstream_supply_chain,
        "get_dockerfiles_for_repos",
        lambda token, rows, *args: downloaded.extend(rows) or rows,
    )
    monkeypatch.setattr(
        upstream_supply_chain,
        "match_images_to_dockerfiles",
        lambda images, dockerfiles, **kwargs: [
            {"repo_url": repo["url"], "match_method": "dockerfile"}
            for repo in dockerfiles
        ],
    )
    monkeypatch.setattr(
        upstream_supply_chain,
        "transform_matches_for_matchlink",
        lambda matches, key: matches,
    )
    monkeypatch.setattr(
        upstream_supply_chain,
        "_get_unmatched_ghcr_image_owner_repos",
        lambda *args: [
            {"repo_url": repo["url"], "image_digest": f"digest-{repo['name']}"}
            for repo in repos
        ],
    )
    monkeypatch.setattr(
        upstream_supply_chain,
        "load_matchlinks",
        lambda session, schema, rows, **kwargs: loaded.extend(rows),
    )
    cleanup_job = Mock()
    cleanup_job.run.side_effect = lambda *args: events.append("cleanup")
    monkeypatch.setattr(
        upstream_supply_chain.GraphJob,
        "from_matchlink",
        lambda *args: cleanup_job,
    )
    monkeypatch.setattr(
        upstream_supply_chain, "run_typed_analysis_job", lambda *args: None
    )
    excluded = {repos[1]["url"]} if exclude else None

    supply_chain.sync(
        Mock(),
        "token",
        "https://api.github.com/graphql",
        "example",
        99,
        {"UPDATE_TAG": 99},
        repos,
        workflows=workflows,
        excluded_repo_urls=excluded,
    )

    expected = {repos[0]["url"]} if exclude else {repo["url"] for repo in repos}
    assert {row["repo_url"] for row in loaded} == expected
    assert {repo["url"] for repo in downloaded} == expected
    assert {row.get("match_method") for row in loaded} == {
        None,
        "provenance",
        "dockerfile",
        "package_owner_repo",
    }
    assert cleanup_job.run.call_count == 4
    if exclude:
        assert events[0] == ("preserve", sorted(excluded))


def test_archived_ruleset_preservation_does_not_revive_stale_active_associations(
    neo4j_session,
):
    from cartography_github.repos import _touch_archived_repo_details
    import cartography.intel.github.repos as upstream_repos

    org_url = "https://github.com/example"
    archived_url = f"{org_url}/archived"
    neo4j_session.run(
        """
        CREATE (org:GitHubOrganization {id: $org_url})
        CREATE (archived:GitHubRepository {id: $archived_url})
        CREATE (active:GitHubRepository {id: $org_url + '/active'})
        CREATE (ruleset:GitHubRuleset {id: 'shared', lastupdated: 1})
        CREATE (rule:GitHubRulesetRule {id: 'rule', lastupdated: 1})
        CREATE (org)-[:RESOURCE {lastupdated: 1}]->(ruleset)
        CREATE (org)-[:RESOURCE {lastupdated: 1}]->(rule)
        CREATE (archived)-[:HAS_RULESET {lastupdated: 1}]->(ruleset)
        CREATE (active)-[:HAS_RULESET {lastupdated: 1}]->(ruleset)
        CREATE (ruleset)-[:CONTAINS_RULE {lastupdated: 1}]->(rule)
        CREATE (ruleset)-[:ANALYSIS_ONLY {lastupdated: 1}]->(active)
        """,
        org_url=org_url,
        archived_url=archived_url,
    ).consume()

    _touch_archived_repo_details(neo4j_session, {archived_url}, 99, org_url)
    upstream_repos.cleanup_rulesets(neo4j_session, {"UPDATE_TAG": 99}, org_url)

    rows = neo4j_session.run(
        """
        MATCH (repo:GitHubRepository)-[rel:HAS_RULESET]->(ruleset)
        MATCH (ruleset)-[contains:CONTAINS_RULE]->(rule)
        MATCH (ruleset)-[analysis:ANALYSIS_ONLY]->()
        RETURN repo.id AS repo_url, rel.lastupdated AS tag,
               rule.lastupdated AS rule_tag, contains.lastupdated AS contains_tag,
               analysis.lastupdated AS analysis_tag
        """
    ).data()
    assert rows == [
        {
            "repo_url": archived_url,
            "tag": 99,
            "rule_tag": 99,
            "contains_tag": 99,
            "analysis_tag": 1,
        }
    ]


def test_archived_codeowners_and_manifest_matches_survive_real_stage_cleanup(
    neo4j_session,
    monkeypatch,
):
    from cartography_github import codeowners

    org_url = "https://github.com/example"
    archived_url = f"{org_url}/archived"
    neo4j_session.run(
        """
        CREATE (org:GitHubOrganization {id: $org_url})
        CREATE (repo:GitHubRepository {id: $archived_url})
        CREATE (rule:GitHubCodeOwnerRule {id: 'rule', lastupdated: 1})
        CREATE (manifest:GitHubDependencyGraphManifest {id: 'manifest'})
        CREATE (org)-[:RESOURCE {lastupdated: 1}]->(rule)
        CREATE (repo)-[:HAS_CODEOWNER_RULE {lastupdated: 1}]->(rule)
        CREATE (manifest)-[:MATCHES_CODEOWNER_RULE {
            lastupdated: 1, _sub_resource_label: 'GitHubOrganization',
            _sub_resource_id: $org_url
        }]->(rule)
        """,
        org_url=org_url,
        archived_url=archived_url,
    ).consume()
    fetch = Mock(side_effect=AssertionError("Archived CODEOWNERS must not be fetched"))
    monkeypatch.setattr(upstream_codeowners, "get_effective_codeowners_file", fetch)

    codeowners.sync(
        neo4j_session,
        {"UPDATE_TAG": 99},
        "token",
        "https://api.github.com/graphql",
        "example",
        [{"id": archived_url, "owner_org_id": org_url}],
        [],
        excluded_repo_urls={archived_url},
    )

    record = neo4j_session.run(
        """
        MATCH ()-[res:RESOURCE]->(rule:GitHubCodeOwnerRule)
        MATCH ()-[owned:HAS_CODEOWNER_RULE]->(rule)
        MATCH ()-[matched:MATCHES_CODEOWNER_RULE]->(rule)
        RETURN rule.lastupdated AS rule, res.lastupdated AS resource,
               owned.lastupdated AS owned, matched.lastupdated AS matched
        """
    ).single()
    assert record is not None
    assert set(record.values()) == {99}
    fetch.assert_not_called()

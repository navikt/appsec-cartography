from datetime import datetime, timezone
import threading
from types import SimpleNamespace

import cartography.intel.github.actions as upstream_actions
import cartography.intel.github.repos as upstream_repos
import cartography.intel.github.commits as upstream_commits
from cartography_github.actions import _touch_skipped_workflows
import cartography_github.actions as local_actions
from cartography_github.commits import _filter_stale_repo_names
import cartography_github.commits as local_commits
import cartography_github.repos as local_repos
from cartography_github.repos import (
    GitHubRepoSyncResult,
    _touch_skipped_manifests,
)


class _RecordingSession:
    def __init__(self, repos=None, workflows=None, bookmark=None):
        self.repos = repos or []
        self.workflows = workflows or []
        self.bookmark = bookmark
        self.db_threads = []

    def execute_read(self, _tx, query, **params):
        self.db_threads.append(threading.get_ident())
        if "manifests_synced_pushedat" in query:
            return [
                {"url": url, "manifests_synced_pushedat": self.bookmark}
                for url in params["repo_urls"]
            ]
        if "RETURN wf.repo_url AS repo_url" in query:
            return self.workflows
        if "RETURN repo.name AS name" in query:
            return self.repos
        raise AssertionError(f"Unexpected read query: {query}")


def _mock_repo_sync_boundary(
    monkeypatch,
    repos,
    incomplete_urls=(),
    *,
    parallel_rulesets=False,
):
    writes = []
    cleanup_calls = []
    caller_thread = threading.get_ident()
    session = _RecordingSession()

    def fake_fetch_all(token, api_url, organization, query, resource, **kwargs):
        if query == upstream_repos.GITHUB_ORG_REPOS_PRIVILEGED_PAGINATED_GRAPHQL:
            return SimpleNamespace(
                nodes=[
                    {
                        **repo,
                        "directCollaborators": {"totalCount": 1},
                        "outsideCollaborators": {"totalCount": 1},
                    }
                    for repo in repos
                    if repo is not None
                ]
            ), None
        return SimpleNamespace(nodes=repos), None

    monkeypatch.setattr(upstream_repos, "fetch_all", fake_fetch_all)
    monkeypatch.setattr(upstream_repos, "_repos_need_privileged_details", lambda _: True)
    monkeypatch.setattr(
        upstream_repos,
        "_merge_repos_with_privileged_details",
        lambda rows, details: (rows, len([r for r in rows if r]), 0),
    )
    monkeypatch.setattr(
        upstream_repos,
        "get_repo_security_and_analysis_by_url",
        lambda *args: {},
    )
    monkeypatch.setattr(
        upstream_repos,
        "transform",
        lambda *args: {
            "repos": [{"owner_org_id": "https://github.com/example"}],
            "dependencies": [],
            "manifests": [],
        },
    )
    monkeypatch.setattr(
        upstream_repos, "enrich_dependencies_with_lockfile_versions", lambda *args: None
    )
    monkeypatch.setattr(upstream_repos, "load", lambda *args: None)
    monkeypatch.setattr(
        upstream_repos, "migrate_dependency_graph_manifest_label", lambda *args: None
    )
    for name in (
        "cleanup_github_branches",
        "cleanup_github_manifests",
        "cleanup_branch_protection_rules",
        "cleanup_rulesets",
    ):
        monkeypatch.setattr(
            upstream_repos,
            name,
            lambda *args, name=name: cleanup_calls.append(name),
        )
    monkeypatch.setattr(
        local_repos,
        "run_analysis_job",
        lambda *args: cleanup_calls.append("analysis"),
    )
    monkeypatch.setattr(
        local_repos,
        "run_write_query",
        lambda session_arg, query, **params: (
            writes.append((query, params, threading.get_ident()))
        ),
    )
    if parallel_rulesets:
        monkeypatch.setattr(
            local_repos,
            "_fetch_rulesets_for_repo",
            lambda repo, *args: (
                repo["url"],
                {"nodes": []},
            ),
        )
    else:
        monkeypatch.setattr(
            local_repos,
            "_get_privileged_details_parallel",
            lambda *args: {
                repo["url"]: {"rulesets": {"nodes": []}}
                for repo in repos
                if repo is not None
            },
        )

    def fetch_collaborators(repo, affiliation, *args):
        return repo["url"], [{"affiliation": affiliation}]

    def fetch_manifest(repo, *args):
        complete = repo["url"] not in incomplete_urls
        return repo["url"], [{"id": repo["name"]}], complete, None

    monkeypatch.setattr(local_repos, "_fetch_collaborators_for_repo", fetch_collaborators)
    monkeypatch.setattr(local_repos, "_fetch_manifest", fetch_manifest)
    return session, writes, cleanup_calls, caller_thread


def test_repository_listing_keeps_raw_fields_and_requests_pushedat(monkeypatch):
    repo = {
        "name": "project",
        "isArchived": False,
        "isDisabled": False,
        "pushedAt": "2026-10-02T00:00:00Z",
    }
    queries = []

    def fake_fetch_all(token, api_url, organization, query, resource, **kwargs):
        queries.append(query)
        return SimpleNamespace(nodes=[repo]), None

    monkeypatch.setattr(local_repos.upstream, "fetch_all", fake_fetch_all)

    result = local_repos._get_repo_data_with_pushedat("token", "api", "example")

    assert result == [repo]
    assert "pushedAt" in queries[0]
    assert result[0]["isArchived"] is False


def test_manifest_bookmark_only_advances_for_complete_repo_fetches(monkeypatch):
    repo_ok = {
        "name": "complete",
        "url": "https://github.com/example/complete",
        "pushedAt": "2026-10-02T00:00:00Z",
    }
    repo_partial = {
        "name": "partial",
        "url": "https://github.com/example/partial",
        "pushedAt": "2026-10-03T00:00:00Z",
    }
    writes = []
    monkeypatch.setattr(
        local_repos,
        "_get_manifests_synced_bookmarks",
        lambda session, urls: {},
    )
    monkeypatch.setattr(local_repos, "_touch_skipped_manifests", lambda *args: None)
    monkeypatch.setattr(
        local_repos,
        "_fetch_manifest",
        lambda repo, *args: (
            repo["url"],
            [{"id": repo["name"]}],
            repo["name"] == "complete",
            None,
        ),
    )
    monkeypatch.setattr(
        local_repos,
        "_update_manifests_synced_bookmarks",
        lambda session, updates: writes.extend(updates),
    )

    data, cleanup_safe = local_repos._get_dep_manifests_for_repos(
        [repo_ok, repo_partial],
        "example",
        "api",
        "token",
        neo4j_session=object(),
        update_tag=12,
        incremental_sync=False,
        parallel_workers=2,
    )

    assert set(data) == {repo_ok["url"], repo_partial["url"]}
    assert cleanup_safe is False
    assert writes == [{"repo_url": repo_ok["url"], "pushedat": repo_ok["pushedAt"]}]


def test_stale_commit_filter_keeps_unknown_and_recent_repositories():
    lookback_date = datetime(2026, 10, 1, tzinfo=timezone.utc)

    eligible = _filter_stale_repo_names(
        ["old", "recent", "unknown", "malformed"],
        {
            "old": "2020-01-01T00:00:00Z",
            "recent": "2026-10-02T00:00:00Z",
            "malformed": "not-a-timestamp",
        },
        lookback_date,
    )

    assert eligible == ["recent", "unknown", "malformed"]


def test_repo_sync_result_exposes_completeness_and_bookmark_fields():
    result = GitHubRepoSyncResult(
        repos=[],
        manifests=[],
        manifests_cleanup_safe=True,
        repo_pushedat_updates=[],
        repos_complete=False,
    )

    assert result.repos_complete is False
    assert result.repo_pushedat_updates == []


def test_repos_sync_runs_parallel_fetches_without_worker_database_access(monkeypatch):
    repos = [
        {
            "name": f"repo-{index}",
            "url": f"https://github.com/example/repo-{index}",
            "pushedAt": f"2026-10-0{index + 1}T00:00:00Z",
            "isArchived": False,
            "isDisabled": False,
        }
        for index in range(2)
    ]
    session, writes, cleanup_calls, caller_thread = _mock_repo_sync_boundary(
        monkeypatch, repos, parallel_rulesets=True
    )
    barrier = threading.Barrier(2)
    worker_threads = {"rulesets": [], "collaborators": [], "manifests": []}

    def run_in_parallel(stage, result):
        worker_threads[stage].append(threading.get_ident())
        barrier.wait(timeout=5)
        return result

    monkeypatch.setattr(
        local_repos,
        "_fetch_rulesets_for_repo",
        lambda repo, *args: run_in_parallel(
            "rulesets", (repo["url"], {"nodes": []})
        ),
    )
    monkeypatch.setattr(
        local_repos,
        "_fetch_collaborators_for_repo",
        lambda repo, affiliation, *args: run_in_parallel(
            "collaborators", (repo["url"], [affiliation])
        ),
    )
    monkeypatch.setattr(
        local_repos,
        "_fetch_manifest",
        lambda repo, *args: run_in_parallel(
            "manifests", (repo["url"], [], True, None)
        ),
    )

    result = local_repos.sync(
        session,
        {"UPDATE_TAG": 21},
        "token",
        "https://api.github.com/graphql",
        "example",
        parallel_workers=2,
        incremental_sync=True,
    )

    assert all(worker_threads[stage] for stage in worker_threads)
    assert all(
        worker_id != caller_thread
        for thread_ids in worker_threads.values()
        for worker_id in thread_ids
    )
    assert session.db_threads == [caller_thread]
    assert writes and {thread_id for _, _, thread_id in writes} == {caller_thread}
    assert set(cleanup_calls) >= {
        "cleanup_github_branches",
        "cleanup_github_manifests",
        "cleanup_branch_protection_rules",
        "cleanup_rulesets",
    }
    assert result.repos == repos
    assert result.repos_complete is True


def test_repos_sync_partial_fetch_and_listing_preserve_bookmarks_and_subgraphs(
    monkeypatch,
):
    repo_complete = {
        "name": "complete",
        "url": "https://github.com/example/complete",
        "pushedAt": "2026-10-01T00:00:00Z",
        "isArchived": False,
        "isDisabled": False,
    }
    repo_incomplete = {
        "name": "incomplete",
        "url": "https://github.com/example/incomplete",
        "pushedAt": "2026-10-02T00:00:00Z",
        "isArchived": False,
        "isDisabled": False,
    }
    session, writes, cleanup_calls, caller_thread = _mock_repo_sync_boundary(
        monkeypatch,
        [repo_complete, repo_incomplete, None],
        incomplete_urls={repo_incomplete["url"]},
    )

    result = local_repos.sync(
        session,
        {"UPDATE_TAG": 22},
        "token",
        "https://api.github.com/graphql",
        "example",
        parallel_workers=2,
        incremental_sync=True,
    )

    manifest_bookmark_writes = [
        params["updates"]
        for query, params, _ in writes
        if "manifests_synced_pushedat" in query
    ]
    assert manifest_bookmark_writes == [
        [{"repo_url": repo_complete["url"], "pushedat": repo_complete["pushedAt"]}]
    ]
    assert result.manifests_cleanup_safe is False
    assert result.repos_complete is False
    assert not {
        "cleanup_github_branches",
        "cleanup_github_manifests",
        "cleanup_branch_protection_rules",
        "cleanup_rulesets",
    }.intersection(cleanup_calls)
    assert {repo["url"] for repo in result.repos} == {
        repo_complete["url"],
        repo_incomplete["url"],
    }
    assert {thread_id for _, _, thread_id in writes} == {caller_thread}


def test_warm_manifest_bookmark_skips_manifest_fetch(monkeypatch):
    repo = {
        "name": "steady",
        "url": "https://github.com/example/steady",
        "pushedAt": "2026-10-01T00:00:00Z",
        "isArchived": False,
        "isDisabled": False,
    }
    session, writes, _, caller_thread = _mock_repo_sync_boundary(monkeypatch, [repo])
    session.bookmark = repo["pushedAt"]
    monkeypatch.setattr(
        upstream_repos,
        "_get_repo_dep_manifests",
        lambda *args: (_ for _ in ()).throw(AssertionError("manifest fetched")),
    )
    monkeypatch.setattr(
        local_repos,
        "_fetch_manifest",
        lambda repo, token, api, org, skip: (
            (repo["url"], [], True, "unchanged")
            if skip
            and repo.get("pushedAt") == repo.get("manifests_synced_pushedat")
            else (_ for _ in ()).throw(AssertionError("manifest fetched"))
        ),
    )

    result = local_repos.sync(
        session,
        {"UPDATE_TAG": 23},
        "token",
        "https://api.github.com/graphql",
        "example",
        parallel_workers=2,
        incremental_sync=True,
    )

    assert result.manifests_cleanup_safe is True
    assert not any("manifests_synced_pushedat" in query for query, _, _ in writes)
    assert {thread_id for _, _, thread_id in writes} == {caller_thread}


def test_archived_manifest_is_not_fetched_or_bookmarked_and_is_touched(monkeypatch):
    repo = {
        "name": "retired",
        "url": "https://github.com/example/retired",
        "pushedAt": "2020-01-01T00:00:00Z",
        "isArchived": True,
        "isDisabled": False,
    }
    touched = []
    bookmarks = []
    monkeypatch.setattr(local_repos, "_get_manifests_synced_bookmarks", lambda *args: {})
    monkeypatch.setattr(
        local_repos,
        "_fetch_manifest",
        lambda *args: (_ for _ in ()).throw(AssertionError("archived repo fetched")),
    )
    monkeypatch.setattr(
        local_repos, "_touch_skipped_manifests", lambda session, urls, tag: touched.extend(urls)
    )
    monkeypatch.setattr(
        local_repos,
        "_update_manifests_synced_bookmarks",
        lambda session, updates: bookmarks.extend(updates),
    )

    manifests, cleanup_safe = local_repos._get_dep_manifests_for_repos(
        [repo],
        "example",
        "api",
        "token",
        neo4j_session=object(),
        update_tag=26,
        incremental_sync=True,
        parallel_workers=2,
    )

    assert manifests == {}
    assert cleanup_safe is True
    assert touched == [repo["url"]]
    assert bookmarks == []


def test_actions_sync_skips_warm_and_archived_workflows_but_refreshes_settings(
    monkeypatch,
):
    caller_thread = threading.get_ident()
    active_url = "https://github.com/example/active"
    archived_url = "https://github.com/example/archived"
    session = _RecordingSession(
        repos=[
            {
                "name": "active",
                "url": active_url,
                "pushedat": "2026-10-01T00:00:00Z",
                "synced_pushedat": "2026-10-01T00:00:00Z",
                "archived": False,
                "disabled": False,
            },
            {
                "name": "archived",
                "url": archived_url,
                "pushedat": "2020-01-01T00:00:00Z",
                "synced_pushedat": "2020-01-01T00:00:00Z",
                "archived": True,
                "disabled": False,
            },
        ],
        workflows=[
            {"repo_url": active_url, "path": ".github/workflows/active.yml"},
            {"repo_url": archived_url, "path": ".github/workflows/archived.yml"},
        ],
    )
    api_calls = []
    loader_calls = []
    write_threads = []
    empty = lambda *args: []
    monkeypatch.setattr(upstream_actions, "get_org_secrets", empty)
    monkeypatch.setattr(upstream_actions, "get_org_variables", empty)

    def settings(name, result):
        def fetch(*args):
            api_calls.append(
                (
                    name,
                    args[3] if len(args) > 3 else None,
                    threading.get_ident(),
                )
            )
            return result

        return fetch

    monkeypatch.setattr(
        upstream_actions,
        "get_repo_workflows",
        lambda *args: (_ for _ in ()).throw(AssertionError("workflow listing fetched")),
    )
    monkeypatch.setattr(
        upstream_actions,
        "get_workflow_content",
        lambda *args: (_ for _ in ()).throw(AssertionError("workflow file fetched")),
    )
    monkeypatch.setattr(
        upstream_actions, "get_repo_environments", settings("environments", [{"id": 5, "name": "prod"}])
    )
    monkeypatch.setattr(upstream_actions, "get_repo_secrets", settings("repo_secrets", [{"name": "S"}]))
    monkeypatch.setattr(upstream_actions, "get_repo_variables", settings("repo_variables", [{"name": "V"}]))
    monkeypatch.setattr(upstream_actions, "get_env_secrets", settings("env_secrets", [{"name": "ES"}]))
    monkeypatch.setattr(upstream_actions, "get_env_variables", settings("env_variables", [{"name": "EV"}]))
    for name in (
        "transform_environments",
        "transform_repo_secrets",
        "transform_repo_variables",
        "transform_env_secrets",
        "transform_env_variables",
    ):
        monkeypatch.setattr(upstream_actions, name, lambda *args, name=name: [name])
    for name in (
        "load_environments",
        "load_repo_secrets",
        "load_repo_variables",
        "load_env_secrets",
        "load_env_variables",
    ):
        monkeypatch.setattr(
            upstream_actions,
            name,
            lambda *args, name=name: loader_calls.append((name, threading.get_ident())),
        )
    monkeypatch.setattr(
        local_actions,
        "run_write_query",
        lambda session_arg, query, **params: write_threads.append(
            threading.get_ident()
        ),
    )
    monkeypatch.setattr(local_actions, "run_analysis_job", lambda *args: None)
    monkeypatch.setattr(upstream_actions, "cleanup_org_level", lambda *args: None)

    workflows = local_actions.sync(
        session,
        {"UPDATE_TAG": 24},
        "token",
        "https://api.github.com",
        "example",
        parallel_workers=2,
        skip_archived_repos=True,
        skip_unchanged_repos=True,
    )

    assert {workflow["repo_url"] for workflow in workflows} == {
        active_url,
        archived_url,
    }
    assert [name for name, _, _ in api_calls] == [
        "environments",
        "repo_secrets",
        "repo_variables",
        "env_secrets",
        "env_variables",
    ]
    assert all(repo_name == "active" for _, repo_name, _ in api_calls)
    assert all(api_thread != caller_thread for _, _, api_thread in api_calls)
    assert len(loader_calls) == 5
    assert all(thread_id == caller_thread for _, thread_id in loader_calls)
    assert session.db_threads and set(session.db_threads) == {caller_thread}
    assert write_threads and set(write_threads) == {caller_thread}


def test_commit_sync_filters_stale_repositories_before_upstream_batch(monkeypatch):
    now = datetime.now(timezone.utc)
    names = ["old", "recent", "unknown"]

    class CommitSession:
        def execute_read(self, _tx, _query, **params):
            urls = params["repo_urls"]
            return [
                {"url": urls[0], "pushedat": "2000-01-01T00:00:00Z"},
                {"url": urls[1], "pushedat": now.isoformat()},
            ]

    calls = []
    monkeypatch.setattr(
        upstream_commits,
        "process_repo_commits_batch",
        lambda *args, **kwargs: calls.append((args[4], kwargs)),
    )
    monkeypatch.setattr(
        upstream_commits,
        "cleanup_github_commit_relationships",
        lambda *args: None,
    )

    local_commits.sync_github_commits(
        CommitSession(),
        "token",
        "https://api.github.com/graphql",
        "example",
        names,
        25,
        lookback_days=30,
        skip_stale_repos=True,
    )

    assert calls[0][0] == ["recent", "unknown"]
    assert calls[0][1]["batch_size"] == 10


def test_touch_skipped_manifests_refreshes_nodes_and_cleanup_relationships(
    neo4j_session,
):
    repo_url = "https://github.com/example/project"
    manifest_id = f"{repo_url}#/requirements.txt"
    neo4j_session.run(
        """
        CREATE (org:GitHubOrganization {id: $org_url})
        CREATE (repo:GitHubRepository {id: $repo_url})
        CREATE (manifest:DependencyGraphManifest {id: $manifest_id, lastupdated: 1})
        CREATE (dependency:Dependency {id: 'dep', lastupdated: 1})
        CREATE (owner_rule:GitHubCodeOwnerRule {id: 'rule'})
        CREATE (org)-[:RESOURCE {lastupdated: 1}]->(manifest)
        CREATE (repo)-[:HAS_MANIFEST {lastupdated: 1}]->(manifest)
        CREATE (manifest)-[:HAS_DEP {lastupdated: 1}]->(dependency)
        CREATE (repo)-[:REQUIRES {lastupdated: 1}]->(dependency)
        CREATE (manifest)-[:MATCHES_CODEOWNER_RULE {lastupdated: 1}]->(owner_rule)
        """,
        org_url="https://github.com/example",
        repo_url=repo_url,
        manifest_id=manifest_id,
    ).consume()

    _touch_skipped_manifests(neo4j_session, [repo_url], 99)

    record = neo4j_session.run(
        """
        MATCH (repo:GitHubRepository {id: $repo_url})-[hm:HAS_MANIFEST]->(m)
        MATCH (org:GitHubOrganization)-[res:RESOURCE]->(m)
        MATCH (m)-[hd:HAS_DEP]->(d:Dependency)
        MATCH (repo)-[req:REQUIRES]->(d)
        MATCH (m)-[mc:MATCHES_CODEOWNER_RULE]->()
        RETURN m.lastupdated AS manifest, hm.lastupdated AS has_manifest,
               res.lastupdated AS resource, d.lastupdated AS dependency,
               hd.lastupdated AS has_dep, req.lastupdated AS requires,
               mc.lastupdated AS codeowner
        """,
        repo_url=repo_url,
    ).single()
    assert record is not None
    assert set(record.values()) == {99}


def test_touch_skipped_workflows_refreshes_nodes_and_cleanup_relationships(
    neo4j_session,
):
    repo_url = "https://github.com/example/project"
    neo4j_session.run(
        """
        CREATE (org:GitHubOrganization {id: 'https://github.com/example'})
        CREATE (repo:GitHubRepository {id: $repo_url})
        CREATE (wf:GitHubWorkflow {id: 'workflow', repo_url: $repo_url, path: '.github/workflows/ci.yml', lastupdated: 1})
        CREATE (action:GitHubAction {id: 'action', lastupdated: 1})
        CREATE (secret:GitHubActionsSecret {id: 'secret'})
        CREATE (org)-[:RESOURCE {lastupdated: 1}]->(wf)
        CREATE (repo)-[:HAS_WORKFLOW {lastupdated: 1}]->(wf)
        CREATE (wf)-[:USES_ACTION {lastupdated: 1}]->(action)
        CREATE (org)-[:RESOURCE {lastupdated: 1}]->(action)
        CREATE (wf)-[:REFERENCES_SECRET {lastupdated: 1}]->(secret)
        """,
        repo_url=repo_url,
    ).consume()

    _touch_skipped_workflows(neo4j_session, [repo_url], 99)

    record = neo4j_session.run(
        """
        MATCH (repo:GitHubRepository {id: $repo_url})-[hw:HAS_WORKFLOW]->(wf)
        MATCH (org:GitHubOrganization)-[res:RESOURCE]->(wf)
        MATCH (wf)-[ua:USES_ACTION]->(action:GitHubAction)
        MATCH (org)-[action_res:RESOURCE]->(action)
        MATCH (wf)-[secret_ref:REFERENCES_SECRET]->()
        RETURN wf.lastupdated AS workflow, hw.lastupdated AS has_workflow,
               res.lastupdated AS resource, action.lastupdated AS action,
               ua.lastupdated AS uses_action, action_res.lastupdated AS action_resource,
               secret_ref.lastupdated AS references_secret
        """,
        repo_url=repo_url,
    ).single()
    assert record is not None
    assert set(record.values()) == {99}


def test_touch_archived_actions_preserves_repo_and_environment_subgraphs(
    neo4j_session,
):
    repo_url = "https://github.com/example/archived"
    neo4j_session.run(
        """
        CREATE (org:GitHubOrganization {id: 'https://github.com/example'})
        CREATE (repo:GitHubRepository {id: $repo_url, archived: true})
        CREATE (wf:GitHubWorkflow {id: 'archived-workflow', lastupdated: 1})
        CREATE (action:GitHubAction {id: 'archived-action', lastupdated: 1})
        CREATE (env:GitHubEnvironment {id: 'archived-env', lastupdated: 1})
        CREATE (secret:GitHubActionsSecret {id: 'archived-secret', lastupdated: 1})
        CREATE (variable:GitHubActionsVariable {id: 'archived-variable', lastupdated: 1})
        CREATE (org)-[:RESOURCE {lastupdated: 1}]->(wf)
        CREATE (repo)-[:HAS_WORKFLOW {lastupdated: 1}]->(wf)
        CREATE (wf)-[:USES_ACTION {lastupdated: 1}]->(action)
        CREATE (org)-[:RESOURCE {lastupdated: 1}]->(action)
        CREATE (repo)-[:HAS_ENVIRONMENT {lastupdated: 1}]->(env)
        CREATE (org)-[:RESOURCE {lastupdated: 1}]->(env)
        CREATE (env)-[:HAS_SECRET {lastupdated: 1}]->(secret)
        CREATE (org)-[:RESOURCE {lastupdated: 1}]->(secret)
        CREATE (repo)-[:HAS_VARIABLE {lastupdated: 1}]->(variable)
        CREATE (org)-[:RESOURCE {lastupdated: 1}]->(variable)
        """,
        repo_url=repo_url,
    ).consume()

    local_actions._touch_archived_actions(neo4j_session, [repo_url], 99)

    record = neo4j_session.run(
        """
        MATCH (repo:GitHubRepository {id: $repo_url})-[hw:HAS_WORKFLOW]->(wf:GitHubWorkflow)
        MATCH (wf)-[ua:USES_ACTION]->(action:GitHubAction)
        MATCH (repo)-[he:HAS_ENVIRONMENT]->(env:GitHubEnvironment)
        MATCH (env)-[hs:HAS_SECRET]->(secret:GitHubActionsSecret)
        MATCH (repo)-[hv:HAS_VARIABLE]->(variable:GitHubActionsVariable)
        RETURN repo.archived AS archived, hw.lastupdated AS workflow_rel,
               wf.lastupdated AS workflow, ua.lastupdated AS action_rel,
               action.lastupdated AS action, he.lastupdated AS environment_rel,
               env.lastupdated AS environment, hs.lastupdated AS secret_rel,
               secret.lastupdated AS secret, hv.lastupdated AS variable_rel,
               variable.lastupdated AS variable
        """,
        repo_url=repo_url,
    ).single()
    assert record is not None
    assert record["archived"] is True
    assert set(value for key, value in record.items() if key != "archived") == {99}

import copy
import os
from unittest.mock import MagicMock

import cartography_nais
import cartography_nais.teams
import cartography_nais.workloads
import tests.data.teams
import tests.data.workloads
from cartography.util import run_analysis_job
from tests.data.workloads import DIGEST
from tests.util import check_rels

NAIS_ANALYSIS_DIR = os.path.join(os.path.dirname(cartography_nais.__file__), "analysis")

TEST_UPDATE_TAG = 123456789
TEST_TENANT_ID = "https://console.nav.cloud.nais.io/query"


def _params(update_tag: int = TEST_UPDATE_TAG) -> dict:
    return {
        "UPDATE_TAG": update_tag,
        "TENANT_ID": TEST_TENANT_ID,
        "NAIS_TENANT_ID": TEST_TENANT_ID,
    }


def _sync(neo4j_session, raw=None, update_tag=TEST_UPDATE_TAG):
    cartography_nais.workloads.sync(
        neo4j_session,
        MagicMock(),
        TEST_TENANT_ID,
        update_tag,
        _params(update_tag),
        _workloads_raw=tests.data.workloads.MOCK_WORKLOADS_RAW if raw is None else raw,
    )


def _run_job(neo4j_session, name: str) -> None:
    run_analysis_job(os.path.join(NAIS_ANALYSIS_DIR, name), neo4j_session, _params())


def test_transform_workloads():
    apps, deployments, links, active = cartography_nais.workloads.transform(
        tests.data.workloads.MOCK_WORKLOADS_RAW
    )
    by_id = {a["id"]: a for a in apps}
    app = by_id["app-1"]
    assert app["environment"] == "prod-gcp"
    assert app["auth_integrations"] == ["EntraID:Entra ID", "TokenX:TokenX"]
    assert app["ingress_types"] == ["INTERNAL"]
    assert app["k8s_deployment_name"] == "my-app"
    assert app["k8s_cronjob_name"] is None
    assert by_id["job-1"]["k8s_deployment_name"] is None
    assert by_id["job-1"]["k8s_cronjob_name"] == "my-job"
    assert by_id["app-2"]["latest_deployment_status"] == "FAILURE"

    deploy_1 = next(d for d in deployments if d["id"] == "deploy-1")
    # The latest status is chosen by timestamp, not list order.
    assert deploy_1["latest_status"] == "SUCCESS"
    assert deploy_1["repository_url"] == "https://github.com/navikt/my-app"
    assert len(links) == 5
    # Newest successful deployment; job-1 has none.
    assert {(a["app_id"], a["deployment_id"]) for a in active} == {
        ("app-1", "deploy-1"),
        ("app-2", "deploy-4"),
    }


def test_transform_compares_timestamps_with_mixed_fractional_precision():
    workload = copy.deepcopy(tests.data.workloads.MOCK_WORKLOADS_RAW[1])
    workload["deployments"] = [
        tests.data.workloads._deployment(
            "older", "2024-06-03T08:00:00Z", [{"state": "SUCCESS", "createdAt": None}]
        ),
        tests.data.workloads._deployment(
            "newer",
            "2024-06-03T08:00:00.500Z",
            [
                {"state": "SUCCESS", "createdAt": "2024-06-03T08:05:00Z"},
                {"state": "FAILURE", "createdAt": "2024-06-03T08:05:00.500Z"},
            ],
        ),
    ]
    apps, deployments, _, active = cartography_nais.workloads.transform([workload])
    assert apps[0]["latest_deployment_status"] == "FAILURE"
    assert [a["deployment_id"] for a in active] == ["older"]


def test_load_workloads_links_controllers_in_the_same_cluster(neo4j_session):
    neo4j_session.run(
        """
        UNWIND ['prod-gcp', 'dev-gcp'] AS cluster
        CREATE (:KubernetesDeployment {
            id: 'deploy-' + cluster, name: 'my-app', namespace: 'team-alpha', cluster_name: cluster
        })
        CREATE (:KubernetesCronJob {
            id: 'cron-' + cluster, name: 'my-job', namespace: 'team-alpha', cluster_name: cluster
        })
        CREATE (:KubernetesDeployment {
            id: 'other-namespace', name: 'my-app', namespace: 'team-beta', cluster_name: 'prod-gcp'
        })
        """
    )
    cartography_nais.teams.sync(
        neo4j_session,
        MagicMock(),
        TEST_TENANT_ID,
        TEST_UPDATE_TAG,
        _params(),
        _teams_raw=tests.data.teams.MOCK_TEAMS_RAW,
    )
    _sync(neo4j_session)

    assert check_rels(
        neo4j_session, "NaisApp", "id", "KubernetesDeployment", "id", "MANAGES"
    ) == {("app-1", "deploy-prod-gcp")}
    assert check_rels(
        neo4j_session, "NaisApp", "id", "KubernetesCronJob", "id", "MANAGES"
    ) == {("job-1", "cron-prod-gcp")}
    assert check_rels(
        neo4j_session, "NaisTeamEnvironment", "id", "NaisApp", "id", "HAS_APP"
    ) == {
        ("teamenv-alpha-prod-gcp", "app-1"),
        ("teamenv-alpha-prod-gcp", "app-2"),
        ("teamenv-alpha-prod-gcp", "job-1"),
    }


def test_load_deployments_and_triggering_github_users(neo4j_session):
    neo4j_session.run(
        """
        CREATE (:GitHubUser {id: 'https://github.com/alice', username: 'alice'})
        CREATE (:GitHubRepository {id: 'https://github.com/navikt/my-app'})
        """
    )
    _sync(neo4j_session)

    assert check_rels(
        neo4j_session, "NaisApp", "id", "NaisDeployment", "id", "ACTIVE_DEPLOYMENT"
    ) == {("app-1", "deploy-1"), ("app-2", "deploy-4")}
    assert len(
        check_rels(neo4j_session, "NaisApp", "id", "NaisDeployment", "id", "HAS_DEPLOYMENT")
    ) == 5
    # Unknown deployers (bob, carol) are skipped.
    assert check_rels(
        neo4j_session, "GitHubUser", "username", "NaisDeployment", "id", "TRIGGERED_BY"
    ) == {("alice", "deploy-1")}
    assert check_rels(
        neo4j_session, "NaisDeployment", "id", "GitHubRepository", "id", "DEPLOYED_FROM"
    ) == {("deploy-old", "https://github.com/navikt/my-app"), ("deploy-1", "https://github.com/navikt/my-app")}


def test_active_deployment_moves_and_stale_links_are_removed(neo4j_session):
    _sync(neo4j_session)

    raw = copy.deepcopy(tests.data.workloads.MOCK_WORKLOADS_RAW)
    newer = copy.deepcopy(raw[0]["deployments"][1])
    newer.update(
        id="deploy-new",
        createdAt="2024-06-05T12:00:00Z",
        statuses=[{"state": "SUCCESS", "createdAt": "2024-06-05T12:01:00Z"}],
    )
    raw[0]["deployments"].append(newer)
    _sync(neo4j_session, raw[:1], TEST_UPDATE_TAG + 1)

    assert check_rels(
        neo4j_session, "NaisApp", "id", "NaisDeployment", "id", "ACTIVE_DEPLOYMENT"
    ) == {("app-1", "deploy-new")}


def test_image_analysis_jobs_link_container_deployment_and_repository(neo4j_session):
    neo4j_session.run(
        """
        CREATE (:GitHubRepository {id: 'https://github.com/navikt/my-app'})
        CREATE (:KubernetesContainer {id: 'container-1', status_image_sha: $digest})
        """,
        digest=DIGEST,
    )
    _sync(neo4j_session)
    for job in (
        "nais_image_digest_link.json",
        "nais_deployed_by.json",
        "nais_built_from_repo.json",
        "nais_gar_link.json",
    ):
        _run_job(neo4j_session, job)

    assert check_rels(
        neo4j_session, "NaisApp", "id", "KubernetesContainer", "id", "RUNS_IMAGE"
    ) == {("app-1", "container-1")}
    assert check_rels(
        neo4j_session, "KubernetesContainer", "id", "NaisDeployment", "id", "DEPLOYED_BY"
    ) == {("container-1", "deploy-1")}
    assert check_rels(
        neo4j_session, "KubernetesContainer", "id", "GitHubRepository", "id", "BUILT_FROM"
    ) == {("container-1", "https://github.com/navikt/my-app")}


def test_ownership_uses_team_namespace_in_each_cluster(neo4j_session):
    neo4j_session.run(
        """
        CREATE (:KubernetesNamespace {id: 'ns-gcp', name: 'team-alpha', cluster_name: 'prod-gcp'})
            -[:CONTAINS]->(:KubernetesPod {id: 'pod-gcp'})
        CREATE (:KubernetesNamespace {id: 'ns-dev', name: 'team-alpha', cluster_name: 'dev-gcp'})
            -[:CONTAINS]->(:KubernetesPod {id: 'pod-dev'})
        """
    )
    cartography_nais.teams.sync(
        neo4j_session,
        MagicMock(),
        TEST_TENANT_ID,
        TEST_UPDATE_TAG,
        _params(),
        _teams_raw=tests.data.teams.MOCK_TEAMS_RAW,
    )
    _run_job(neo4j_session, "nais_ownership.json")

    assert check_rels(
        neo4j_session, "NaisTeam", "slug", "KubernetesPod", "id", "RESPONSIBLE_FOR"
    ) == {("team-alpha", "pod-gcp")}

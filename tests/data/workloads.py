"""Mock Nais workloads in the shape returned by cartography_nais.workloads.get_workloads()."""

DIGEST = "sha256:aaaa1111bbbb2222cccc3333dddd4444eeee5555ffff6666aaaa1111bbbb2222"

TEAM_ENVIRONMENT = {
    "id": "teamenv-alpha-prod-gcp",
    "environment": {"name": "prod-gcp"},
}


def _deployment(id, created_at, statuses, repository=None, deployer=None, sha=None):
    return {
        "id": id,
        "createdAt": created_at,
        "teamSlug": "team-alpha",
        "environmentName": "prod-gcp",
        "repository": repository,
        "deployerUsername": deployer,
        "commitSha": sha,
        "triggerUrl": None,
        "statuses": statuses,
    }


MOCK_WORKLOADS_RAW = [
    {
        "__typename": "Application",
        "id": "app-1",
        "name": "my-app",
        "deletionStartedAt": None,
        "appState": "RUNNING",
        "team": {"slug": "team-alpha"},
        "teamEnvironment": TEAM_ENVIRONMENT,
        "image": {"name": "ghcr.io/navikt/my-app", "tag": "abc123", "digest": DIGEST},
        "ingresses": [{"url": "https://my-app.intern.nav.no", "type": "INTERNAL"}],
        "appAuth": [
            {"__typename": "TokenXAuthIntegration", "name": "TokenX"},
            {"__typename": "EntraIDAuthIntegration", "name": "Entra ID"},
        ],
        # Unordered on purpose: the API does not document the order.
        "deployments": [
            _deployment(
                "deploy-old",
                "2024-05-30T12:00:00Z",
                [{"state": "SUCCESS", "createdAt": "2024-05-30T12:01:00Z"}],
                "navikt/my-app",
                "bob",
                "oldhash123",
            ),
            _deployment(
                "deploy-1",
                "2024-06-01T12:00:00Z",
                [
                    {"state": "SUCCESS", "createdAt": "2024-06-01T12:02:00Z"},
                    {"state": "IN_PROGRESS", "createdAt": "2024-06-01T12:01:00Z"},
                ],
                "navikt/my-app",
                "alice",
                "abc123def456",
            ),
        ],
    },
    {
        # Newest deployment failed; the previous successful one is still active.
        "__typename": "Application",
        "id": "app-2",
        "name": "my-failing-app",
        "deletionStartedAt": None,
        "appState": "NOT_RUNNING",
        "team": {"slug": "team-alpha"},
        "teamEnvironment": TEAM_ENVIRONMENT,
        "image": {"name": "ghcr.io/navikt/my-failing-app", "tag": "xyz789", "digest": None},
        "ingresses": [],
        "appAuth": [],
        "deployments": [
            _deployment(
                "deploy-3",
                "2024-06-03T08:00:00Z",
                [{"state": "FAILURE", "createdAt": "2024-06-03T08:05:00Z"}],
                "navikt/my-failing-app",
                "carol",
            ),
            _deployment(
                "deploy-4",
                "2024-06-02T08:00:00Z",
                [{"state": "SUCCESS", "createdAt": "2024-06-02T08:05:00Z"}],
                "navikt/my-failing-app",
                "carol",
            ),
        ],
    },
    {
        "__typename": "Job",
        "id": "job-1",
        "name": "my-job",
        "deletionStartedAt": None,
        "jobState": "COMPLETED",
        "team": {"slug": "team-alpha"},
        "teamEnvironment": TEAM_ENVIRONMENT,
        "image": {"name": "ghcr.io/navikt/my-job", "tag": "def456", "digest": None},
        "schedule": {"expression": "0 3 * * *"},
        "jobAuth": [{"__typename": "MaskinportenAuthIntegration", "name": "Maskinporten"}],
        # No status yet: no active deployment.
        "deployments": [_deployment("deploy-2", "2024-06-02T10:00:00Z", [])],
    },
]

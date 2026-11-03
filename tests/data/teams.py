"""Mock Nais teams in the shape returned by cartography_nais.teams.get()."""

MOCK_TEAMS_RAW = [
    {
        "id": "team-1",
        "slug": "team-alpha",
        "purpose": "Alpha team",
        "slackChannel": "#alpha",
        "lastSuccessfulSync": "2024-01-01T00:00:00Z",
        "deletionInProgress": False,
        "externalResources": {
            "entraIDGroup": {"groupID": "entra-group-aaa"},
            "gitHubTeam": {"slug": "team-alpha"},
            "googleGroup": {"email": "team-alpha@nav.no"},
            "googleArtifactRegistry": {
                "repository": "europe-north1-docker.pkg.dev/nais-management/team-alpha"
            },
        },
        "environments": [
            {
                "id": "teamenv-alpha-prod-gcp",
                "gcpProjectID": "team-alpha-prod-1234",
                "environment": {"name": "prod-gcp"},
            },
            {
                "id": "teamenv-alpha-prod-fss",
                "gcpProjectID": None,
                "environment": {"name": "prod-fss"},
            },
        ],
        "members": [
            {
                "role": "OWNER",
                "user": {
                    "id": "user-1",
                    "email": "Alice@NAV.no ",
                    "name": "Alice",
                    "externalID": "100000000000000000001",
                    "isAdmin": False,
                },
            },
            {
                "role": "MEMBER",
                "user": {
                    "id": "user-2",
                    "email": "bob@nav.no",
                    "name": "Bob",
                    "externalID": "100000000000000000002",
                    "isAdmin": True,
                },
            },
        ],
    },
    {
        "id": "team-2",
        "slug": "team-beta",
        "purpose": "Beta team",
        "slackChannel": "#beta",
        "lastSuccessfulSync": None,
        "deletionInProgress": False,
        "externalResources": {
            "entraIDGroup": None,
            "gitHubTeam": None,
            "googleGroup": None,
            "googleArtifactRegistry": None,
        },
        "environments": [],
        "members": [
            {
                "role": "MEMBER",
                "user": {
                    "id": "user-2",
                    "email": "bob@nav.no",
                    "name": "Bob",
                    "externalID": "100000000000000000002",
                    "isAdmin": True,
                },
            },
        ],
    },
]

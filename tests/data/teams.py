"""Mock data for NAIS teams and members tests."""

MOCK_TEAMS_RAW = [
    {
        "id": "team-1",
        "slug": "team-alpha",
        "purpose": "Alpha team",
        "slackChannel": "#alpha",
        "lastSuccessfulSync": "2024-01-01T00:00:00Z",
        "externalResources": {
            "entraIDGroup": {"groupID": "entra-group-aaa"},
            "gitHubTeam": {"slug": "team-alpha"},
            "googleGroup": {"email": "team-alpha@nav.no"},
        },
        "members": {
            "nodes": [
                {
                    "role": "OWNER",
                    "user": {
                        "id": "user-1",
                        "email": "alice@nav.no",
                        "name": "Alice",
                        "externalID": "ext-alice",
                    },
                },
                {
                    "role": "MEMBER",
                    "user": {
                        "id": "user-2",
                        "email": "bob@nav.no",
                        "name": "Bob",
                        "externalID": "ext-bob",
                    },
                },
            ]
        },
    },
    {
        "id": "team-2",
        "slug": "team-beta",
        "purpose": "Beta team",
        "slackChannel": "#beta",
        "lastSuccessfulSync": None,
        "externalResources": {
            "entraIDGroup": None,
            "gitHubTeam": None,
            "googleGroup": None,
        },
        "members": {
            "nodes": [
                {
                    "role": "MEMBER",
                    "user": {
                        "id": "user-2",
                        "email": "bob@nav.no",
                        "name": "Bob",
                        "externalID": "ext-bob",
                    },
                },
            ]
        },
    },
]

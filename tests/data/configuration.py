"""Mock Nais secret and config metadata in the shape returned by configuration.get()."""

TEAM_ENVIRONMENT = {
    "id": "teamenv-alpha-prod-gcp",
    "environment": {"name": "prod-gcp"},
}

MOCK_CONFIGURATION_RAW = [
    {
        "id": "team-1",
        "slug": "team-alpha",
        "secrets": [
            {
                "id": "secret-1",
                "name": "my-app-secrets",
                "lastModifiedAt": "2024-06-01T00:00:00Z",
                "lastModifiedBy": {"id": "user-1"},
                "teamEnvironment": TEAM_ENVIRONMENT,
                "workloads": [{"id": "app-1"}, {"id": "job-1"}],
                "keys": ["PASSWORD", "API_KEY"],
            }
        ],
        "configs": [
            {
                "id": "config-1",
                "name": "my-app-config",
                "lastModifiedAt": None,
                "lastModifiedBy": None,
                "teamEnvironment": TEAM_ENVIRONMENT,
                "workloads": [{"id": "app-1"}],
                "values": [{"name": "LOG_LEVEL"}, {"name": "FEATURE_X"}],
            }
        ],
    }
]

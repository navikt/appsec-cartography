# Nais collector

Runs as `cartography-nais` alongside unmodified upstream Cartography. It ingests
only what the native modules cannot see. Kubernetes, GCP and GitHub resources
come from their upstream modules, and the collector links to them.

## Graph

- `NaisTeam` with `HAS_MEMBER {role}` to `NaisMember`, and links to its Entra ID
  group, GitHub team and Google group.
- `NaisTeamEnvironment` per team and environment, linked to the team's
  `KubernetesNamespace` in that cluster and to its `GCPProject`.
- `NaisApp` for each Application and Naisjob, with state, ingresses and auth
  integrations, linked with `MANAGES` to its `KubernetesDeployment` or
  `KubernetesCronJob`. Unscheduled Naisjobs are not linked yet.
- `NaisDeployment` for each deploy event, with repository, commit, deployer and
  latest status. `ACTIVE_DEPLOYMENT` points to the newest successful one.
- `NaisSecret` and `NaisConfig` with key names, last modifier and the workloads
  that use them. Values are never requested.

`NaisMember` is a `UserAccount` with `email` and `normalized_email`. The nav.no
address identifies the same person across modules, so the upstream ontology
links it to `User` once a users source is configured.

## Secrets

The Kubernetes [cluster role](../.nais/cartography-clusterrole.yaml) never
grants `secrets`, because listing secrets exposes their values. Secret metadata
comes from the Nais API instead.

## Development

Run `mise install`, then `uv sync --locked --extra test`. Test with
`uv run --locked --extra test pytest` (requires Docker), and see
`uv run --locked cartography-nais --help` for options.

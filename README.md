# appsec-cartography

Repo that builds and deploys [Cartography](https://github.com/cartography-cncf/cartography)
with our local Nais and GitHub collectors.

## Releases

[Build & deploy Cartography](.github/workflows/build-deploy-cartography.yaml)
runs on deployment configuration changes on `main`, or manually from Actions.
GCP, Kubernetes, and Nais use the latest stable upstream release; GitHub uses
the tested upstream `0.143.0` release with a local collector extension.
See the workflow matrix for sources and cluster targets,
[Dockerfile.cartography](Dockerfile.cartography) for the build, and [.nais](.nais)
for deployment settings.

To roll back, run **Deploy existing Cartography image** on `main` with an image
reference from a previous run summary. Neo4j is built and deployed separately
through **Build & deploy Neo4j**.

The local [Nais collector](cartography_nais) runs as `cartography-nais` alongside
unmodified upstream Cartography. Run `mise install`, then
`uv sync --locked --extra test` to set up development.
Use `uv run --locked --extra test pytest` to test (requires Docker),
and `uv run --locked cartography-nais --help` for collector options.

The local [GitHub collector](cartography_github) runs as `cartography-github`.
It extracts the incremental and parallel collection from
`navikt/cartography@github-module` while reusing upstream transforms, models,
and unaffected ingestion stages. GitHub API fetches run with four workers by
default; Neo4j writes stay on the ingestion thread.

Incremental sync preserves existing workflow and dependency subgraphs when a
repository's push timestamp is unchanged, refreshing cleanup timestamps on
their nodes and relationships. Secrets, variables, and environments are still
refreshed for active repositories. Commit queries skip repositories with no
push in the lookback window. Bookmarks advance only after successful processing;
incomplete dependency responses remain eligible for retry. A first run without
compatible bookmarks still performs a full collection.

Use `--no-github-incremental-sync` for a full refresh, and
`--github-parallel-workers N` to change API concurrency. This is a local
collector, not a patch of the installed upstream modules. GitHub is pinned
because the extension uses upstream internal helpers; run the tests against
the selected source before updating the pin.

Scheduled GitHub runs remain paused pending production verification. Run the
Naisjob manually after deployment to check runtime, completeness warnings,
and the logged stage durations before restoring its schedule. The previous
baseline fetch cache is no longer read or written; existing
`AppsecGitHubFetchCache` nodes are left untouched.

### Kubernetes

The [cluster role and binding](.nais/cartography-clusterrole.yaml) must be applied
by the platform team. Collector schedules are staggered to avoid concurrent
database updates.

## Contact

For any questions, issues, or feature requests, please reach out to the AppSec team:
- Internal: Either our slack channel [#appsec](https://nav-it.slack.com/archives/C06P91VN27M) or contact a [team member](https://teamkatalogen.nav.no/team/02ed767d-ce01-49b5-9350-ee4c984fd78f) directly via slack/teams/mail.
- External: [Open GitHub Issue](https://github.com/navikt/appsec-guide/issues/new/choose)

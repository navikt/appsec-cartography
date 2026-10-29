# appsec-cartography

Repo that builds and deploys [Cartography](https://github.com/cartography-cncf/cartography)
with our local Nais and GitHub collectors.

## Releases

[Build & deploy Cartography](.github/workflows/build-deploy-cartography.yaml)
runs on deployment configuration changes on `main`, or manually from Actions.
GCP, Kubernetes, and Nais use the latest stable upstream release; GitHub uses
upstream `master`. See the workflow matrix for sources and cluster targets,
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

The local [GitHub collector](cartography_github) runs as `cartography-github`. It
runs upstream GitHub ingestion unchanged, but replays cached API responses for
repositories whose default branch has not moved: file contents (workflows,
CODEOWNERS, lockfiles) and dependency graph manifests. It also skips commit
queries for repositories with no push in the lookback window. Upstream still
transforms, loads, and cleans up every run. The cache lives in Neo4j as
`AppsecGitHubFetchCache` nodes, expires after about seven days, and is ignored
when the wrapped upstream code changes. Use `--no-fetch-cache` to run plain
upstream ingestion.

### Kubernetes

The [cluster role and binding](.nais/cartography-clusterrole.yaml) must be applied
by the platform team. Collector schedules are staggered to avoid concurrent
database updates.

## Contact

For any questions, issues, or feature requests, please reach out to the AppSec team:
- Internal: Either our slack channel [#appsec](https://nav-it.slack.com/archives/C06P91VN27M) or contact a [team member](https://teamkatalogen.nav.no/team/02ed767d-ce01-49b5-9350-ee4c984fd78f) directly via slack/teams/mail.
- External: [Open GitHub Issue](https://github.com/navikt/appsec-guide/issues/new/choose)

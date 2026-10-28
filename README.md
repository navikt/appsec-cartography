# appsec-cartography

Repo that builds and deploys [Cartography](https://github.com/cartography-cncf/cartography)
and our [custom collectors](https://github.com/navikt/cartography).

## Releases

[Build & deploy Cartography](.github/workflows/build-deploy-cartography.yaml)
runs on deployment configuration changes on `main`, or manually from Actions.
GCP and Kubernetes use the latest stable upstream release; Nais and GitHub use
our custom fork branches. See the workflow matrix for sources and cluster targets,
[Dockerfile.cartography](Dockerfile.cartography) for the build, and [.nais](.nais)
for deployment settings.

To roll back, run **Deploy existing Cartography image** on `main` with an image
reference from a previous run summary. Neo4j is built and deployed separately
through **Build & deploy Neo4j**.

### Kubernetes

The [cluster role and binding](.nais/cartography-clusterrole.yaml) must be applied
by the platform team. Collector schedules are staggered to avoid concurrent
database updates.

## Contact

For any questions, issues, or feature requests, please reach out to the AppSec team:
- Internal: Either our slack channel [#appsec](https://nav-it.slack.com/archives/C06P91VN27M) or contact a [team member](https://teamkatalogen.nav.no/team/02ed767d-ce01-49b5-9350-ee4c984fd78f) directly via slack/teams/mail.
- External: [Open GitHub Issue](https://github.com/navikt/appsec-guide/issues/new/choose)

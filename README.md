# appsec-cartography

Repo that hosts and deploys dockerfiles related to our fork of [Cartography](https://github.com/navikt/cartography).

## Releases

**Build & deploy Cartography** runs daily, on deployment configuration changes on
`main`, or manually from the Actions tab. Its source/target matrix is the only
release configuration:

| Source branch in `navikt/cartography` | Collectors | Clusters |
|---|---|---|
| `master` | GCP, Kubernetes | GCP in prod-gcp; Kubernetes in all four clusters |
| `nais-module` | Nais | prod-gcp |
| `github-module` | GitHub | prod-gcp |

The reusable workflow builds each branch once using its existing `nais.Dockerfile`,
pulls fresh base images, and publishes to the Nav registry with the standard Nais
SBOM and signing. After a CLI smoke test, it deploys the same image digest to that
branch's targets. Source commits and image references are recorded in the run
summary. No cross-repository write credentials or fork workflow dispatches are needed.

Python dependencies still come from each branch's `uv.lock`: merge dependency
updates into the relevant source branch to release them. Rebuilding alone does
not upgrade locked dependencies. Once the Nav modules share a source branch,
combine their target lists in the matrix to build one shared image.

For an urgent release, run **Build & deploy Cartography** on `main`. To retry a
partial release, use **Re-run failed jobs**. To roll back, use a collector's existing
manual deployment workflow with a previous image reference from a run summary.
Wait for or cancel an active release before rolling back. Deploying updates the
scheduled job definition; ingestion happens at the existing schedule.

Neo4j remains independent: run **Build & deploy Neo4j** explicitly when its image
needs updating. Collector releases do not restart Neo4j or modify its storage.

#### Kubernetes
Cartography-k8s requires a custom clusterrole + binding applied by platform, as documented [here](.nais/cartography-clusterrole.yaml). K8s jobs are deployed in a staggered fashion to avoid race conditions when updating the database.

## Contact

For any questions, issues, or feature requests, please reach out to the AppSec team:
- Internal: Either our slack channel [#appsec](https://nav-it.slack.com/archives/C06P91VN27M) or contact a [team member](https://teamkatalogen.nav.no/team/02ed767d-ce01-49b5-9350-ee4c984fd78f) directly via slack/teams/mail.
- External: [Open GitHub Issue](https://github.com/navikt/appsec-guide/issues/new/choose)

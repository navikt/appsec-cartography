# appsec-cartography

Builds and deploys [Cartography](https://github.com/cartography-cncf/cartography)
with our local [Nais](cartography_nais) and [GitHub](cartography_github) collectors.
Upstream modules cover GCP and Kubernetes, and `cartography-link` runs the
upstream `ontology` stage after all collectors to link data across sources.

- Deploy: [Build & deploy Cartography](.github/workflows/build-deploy-cartography.yaml);
  roll back with **Deploy existing Cartography image**. Settings are in [.nais](.nais).
- Kubernetes access: the platform team applies the
  [cluster role](.nais/cartography-clusterrole.yaml). Never grant `secrets`.
- Develop: `mise install`, `uv sync --locked --extra test`, then
  `uv run --locked --extra test pytest` (requires Docker).

## Contact

For any questions, issues, or feature requests, please reach out to the AppSec team:
- Internal: Either our slack channel [#appsec](https://nav-it.slack.com/archives/C06P91VN27M) or contact a [team member](https://teamkatalogen.nav.no/team/02ed767d-ce01-49b5-9350-ee4c984fd78f) directly via slack/teams/mail.
- External: [Open GitHub Issue](https://github.com/navikt/appsec-guide/issues/new/choose)

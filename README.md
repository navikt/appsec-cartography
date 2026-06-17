# appsec-cartography

Repo that hosts and deploys dockerfiles related to our fork of [Cartography](https://github.com/navikt/cartography).


#### Kubernetes
Cartography-k8s requires a custom clusterrole + binding applied by platform, as documented [here](.nais/cartography-clusterrole.yaml). K8s jobs are deployed in a staggered fashion to avoid race conditions when updating the database.

## Contact

For any questions, issues, or feature requests, please reach out to the AppSec team:
- Internal: Either our slack channel [#appsec](https://nav-it.slack.com/archives/C06P91VN27M) or contact a [team member](https://teamkatalogen.nav.no/team/02ed767d-ce01-49b5-9350-ee4c984fd78f) directly via slack/teams/mail.
- External: [Open GitHub Issue](https://github.com/navikt/appsec-guide/issues/new/choose)

from dataclasses import dataclass

from cartography.models.core.common import PropertyRef
from cartography.models.core.nodes import CartographyNodeProperties
from cartography.models.core.nodes import CartographyNodeSchema
from cartography.models.core.relationships import CartographyRelSchema
from cartography.models.core.relationships import LinkDirection
from cartography.models.core.relationships import make_source_node_matcher
from cartography.models.core.relationships import make_target_node_matcher
from cartography.models.core.relationships import OtherRelationships
from cartography.models.core.relationships import SourceNodeMatcher
from cartography.models.core.relationships import TargetNodeMatcher
from cartography_nais.models.team import NaisMatchLinkRelProperties
from cartography_nais.models.team import NaisRelProperties
from cartography_nais.models.team import NaisTenantRel

# ---------------------------------------------------------------------------
# NaisApp: the desired Nais workload (Application or Naisjob)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NaisAppNodeProperties(CartographyNodeProperties):
    id: PropertyRef = PropertyRef("id")
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)
    name: PropertyRef = PropertyRef("name", extra_index=True)
    workload_type: PropertyRef = PropertyRef("workload_type")  # Application | Job
    team_slug: PropertyRef = PropertyRef("team_slug", extra_index=True)
    environment: PropertyRef = PropertyRef("environment", extra_index=True)
    # Desired image from the Nais manifest; the observed image comes from Kubernetes.
    image_name: PropertyRef = PropertyRef("image_name")
    image_tag: PropertyRef = PropertyRef("image_tag")
    image_digest: PropertyRef = PropertyRef("image_digest")
    state: PropertyRef = PropertyRef("state")
    ingresses: PropertyRef = PropertyRef("ingresses")
    ingress_types: PropertyRef = PropertyRef("ingress_types")
    auth_integrations: PropertyRef = PropertyRef("auth_integrations")
    schedule: PropertyRef = PropertyRef("schedule")
    deletion_started_at: PropertyRef = PropertyRef("deletion_started_at")
    latest_deployment_status: PropertyRef = PropertyRef("latest_deployment_status")


@dataclass(frozen=True)
# (:NaisTeam)-[:HAS_APP]->(:NaisApp)
class NaisAppToTeamRel(CartographyRelSchema):
    target_node_label: str = "NaisTeam"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"slug": PropertyRef("team_slug")},
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "HAS_APP"
    properties: NaisRelProperties = NaisRelProperties()


@dataclass(frozen=True)
# (:NaisTeamEnvironment)-[:HAS_APP]->(:NaisApp)
class NaisAppToTeamEnvironmentRel(CartographyRelSchema):
    target_node_label: str = "NaisTeamEnvironment"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("team_environment_id")},
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "HAS_APP"
    properties: NaisRelProperties = NaisRelProperties()


@dataclass(frozen=True)
# (:NaisApp)-[:MANAGES]->(:KubernetesDeployment)
class NaisAppToKubernetesDeploymentRel(CartographyRelSchema):
    target_node_label: str = "KubernetesDeployment"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {
            "cluster_name": PropertyRef("environment"),
            "namespace": PropertyRef("team_slug"),
            "name": PropertyRef("k8s_deployment_name"),
        },
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "MANAGES"
    properties: NaisRelProperties = NaisRelProperties()


@dataclass(frozen=True)
# (:NaisApp)-[:MANAGES]->(:KubernetesCronJob)
class NaisAppToKubernetesCronJobRel(CartographyRelSchema):
    target_node_label: str = "KubernetesCronJob"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {
            "cluster_name": PropertyRef("environment"),
            "namespace": PropertyRef("team_slug"),
            "name": PropertyRef("k8s_cronjob_name"),
        },
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "MANAGES"
    properties: NaisRelProperties = NaisRelProperties()


@dataclass(frozen=True)
class NaisAppSchema(CartographyNodeSchema):
    label: str = "NaisApp"
    properties: NaisAppNodeProperties = NaisAppNodeProperties()
    sub_resource_relationship: NaisTenantRel = NaisTenantRel()
    other_relationships: OtherRelationships = OtherRelationships(
        [
            NaisAppToTeamRel(),
            NaisAppToTeamEnvironmentRel(),
            NaisAppToKubernetesDeploymentRel(),
            NaisAppToKubernetesCronJobRel(),
        ]
    )


# ---------------------------------------------------------------------------
# NaisDeployment: a deploy event (repository, commit, actor and result)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NaisDeploymentNodeProperties(CartographyNodeProperties):
    id: PropertyRef = PropertyRef("id")
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)
    created_at: PropertyRef = PropertyRef("created_at")
    team_slug: PropertyRef = PropertyRef("team_slug", extra_index=True)
    environment_name: PropertyRef = PropertyRef("environment_name")
    repository: PropertyRef = PropertyRef("repository", extra_index=True)
    deployer_username: PropertyRef = PropertyRef("deployer_username")
    commit_sha: PropertyRef = PropertyRef("commit_sha", extra_index=True)
    trigger_url: PropertyRef = PropertyRef("trigger_url")
    latest_status: PropertyRef = PropertyRef("latest_status")
    latest_status_at: PropertyRef = PropertyRef("latest_status_at")


@dataclass(frozen=True)
# (:NaisTeam)-[:HAS_DEPLOYMENT]->(:NaisDeployment)
class NaisDeploymentToTeamRel(CartographyRelSchema):
    target_node_label: str = "NaisTeam"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"slug": PropertyRef("team_slug")},
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "HAS_DEPLOYMENT"
    properties: NaisRelProperties = NaisRelProperties()


@dataclass(frozen=True)
# (:NaisDeployment)-[:DEPLOYED_FROM]->(:GitHubRepository)
class NaisDeploymentToGitHubRepoRel(CartographyRelSchema):
    target_node_label: str = "GitHubRepository"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("repository_url")},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "DEPLOYED_FROM"
    properties: NaisRelProperties = NaisRelProperties()


@dataclass(frozen=True)
class NaisDeploymentSchema(CartographyNodeSchema):
    label: str = "NaisDeployment"
    properties: NaisDeploymentNodeProperties = NaisDeploymentNodeProperties()
    sub_resource_relationship: NaisTenantRel = NaisTenantRel()
    other_relationships: OtherRelationships = OtherRelationships(
        [
            NaisDeploymentToTeamRel(),
            NaisDeploymentToGitHubRepoRel(),
        ]
    )


@dataclass(frozen=True)
# (:NaisApp)-[:HAS_DEPLOYMENT]->(:NaisDeployment), from the workload's deployment list
class NaisAppToDeploymentMatchLink(CartographyRelSchema):
    target_node_label: str = "NaisDeployment"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("deployment_id")},
    )
    source_node_label: str = "NaisApp"
    source_node_matcher: SourceNodeMatcher = make_source_node_matcher(
        {"id": PropertyRef("app_id")},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "HAS_DEPLOYMENT"
    properties: NaisMatchLinkRelProperties = NaisMatchLinkRelProperties()


@dataclass(frozen=True)
# (:NaisApp)-[:ACTIVE_DEPLOYMENT]->(:NaisDeployment): newest successful deployment
class NaisAppToActiveDeploymentMatchLink(CartographyRelSchema):
    target_node_label: str = "NaisDeployment"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("deployment_id")},
    )
    source_node_label: str = "NaisApp"
    source_node_matcher: SourceNodeMatcher = make_source_node_matcher(
        {"id": PropertyRef("app_id")},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "ACTIVE_DEPLOYMENT"
    properties: NaisMatchLinkRelProperties = NaisMatchLinkRelProperties()


@dataclass(frozen=True)
# (:GitHubUser)-[:TRIGGERED_BY]->(:NaisDeployment), matched on GitHub username.
# Skipped when the user is unknown (bots, outside collaborators, GitHub not synced).
class NaisDeploymentToGitHubUserRel(CartographyRelSchema):
    target_node_label: str = "NaisDeployment"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("deployment_id")},
    )
    source_node_label: str = "GitHubUser"
    source_node_matcher: SourceNodeMatcher = make_source_node_matcher(
        {"username": PropertyRef("deployer_username")},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "TRIGGERED_BY"
    properties: NaisMatchLinkRelProperties = NaisMatchLinkRelProperties()

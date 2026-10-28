from dataclasses import dataclass

from cartography.models.core.common import PropertyRef
from cartography.models.core.nodes import CartographyNodeProperties
from cartography.models.core.nodes import CartographyNodeSchema
from cartography.models.core.relationships import CartographyRelProperties
from cartography.models.core.relationships import CartographyRelSchema
from cartography.models.core.relationships import LinkDirection
from cartography.models.core.relationships import make_source_node_matcher
from cartography.models.core.relationships import make_target_node_matcher
from cartography.models.core.relationships import OtherRelationships
from cartography.models.core.relationships import SourceNodeMatcher
from cartography.models.core.relationships import TargetNodeMatcher

# ---------------------------------------------------------------------------
# NaisApp (Application + Job workloads)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NaisAppNodeProperties(CartographyNodeProperties):
    id: PropertyRef = PropertyRef("id")
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)
    name: PropertyRef = PropertyRef("name", extra_index=True)
    workload_type: PropertyRef = PropertyRef("workload_type")  # "Application" or "Job"
    team_slug: PropertyRef = PropertyRef("team_slug", extra_index=True)
    environment: PropertyRef = PropertyRef("environment", extra_index=True)
    gcp_project_id: PropertyRef = PropertyRef("gcp_project_id")
    image_name: PropertyRef = PropertyRef("image_name")
    image_tag: PropertyRef = PropertyRef("image_tag")
    image_digest: PropertyRef = PropertyRef("image_digest")
    state: PropertyRef = PropertyRef("state")
    ingresses: PropertyRef = PropertyRef("ingresses")
    has_running_instance: PropertyRef = PropertyRef("has_running_instance")


@dataclass(frozen=True)
class NaisAppToTenantRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisApp)<-[:RESOURCE]-(:NaisTenant)
class NaisAppToTenantRel(CartographyRelSchema):
    target_node_label: str = "NaisTenant"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("NAIS_TENANT_ID", set_in_kwargs=True)},
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "RESOURCE"
    properties: NaisAppToTenantRelProperties = NaisAppToTenantRelProperties()


@dataclass(frozen=True)
class NaisAppToTeamRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisTeam)-[:HAS_APP]->(:NaisApp)
class NaisAppToTeamRel(CartographyRelSchema):
    target_node_label: str = "NaisTeam"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"slug": PropertyRef("team_slug")},
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "HAS_APP"
    properties: NaisAppToTeamRelProperties = NaisAppToTeamRelProperties()


@dataclass(frozen=True)
class NaisAppToKubernetesNamespaceRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisApp)-[:RUNS_IN]->(:KubernetesNamespace)
# Matched by namespace.name = team slug (NAIS convention)
class NaisAppToKubernetesNamespaceRel(CartographyRelSchema):
    target_node_label: str = "KubernetesNamespace"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"name": PropertyRef("team_slug")},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "RUNS_IN"
    properties: NaisAppToKubernetesNamespaceRelProperties = (
        NaisAppToKubernetesNamespaceRelProperties()
    )


@dataclass(frozen=True)
class NaisAppSchema(CartographyNodeSchema):
    label: str = "NaisApp"
    properties: NaisAppNodeProperties = NaisAppNodeProperties()
    sub_resource_relationship: NaisAppToTenantRel = NaisAppToTenantRel()
    other_relationships: OtherRelationships = OtherRelationships(
        [
            NaisAppToTeamRel(),
            NaisAppToKubernetesNamespaceRel(),
        ]
    )


# ---------------------------------------------------------------------------
# NaisDeployment  (the GitHub→NAIS event link)
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
    commit_sha: PropertyRef = PropertyRef("commit_sha")
    trigger_url: PropertyRef = PropertyRef("trigger_url")
    latest_status: PropertyRef = PropertyRef("latest_status")
    is_active: PropertyRef = PropertyRef("is_active")


@dataclass(frozen=True)
class NaisDeploymentToTenantRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisDeployment)<-[:RESOURCE]-(:NaisTenant)
class NaisDeploymentToTenantRel(CartographyRelSchema):
    target_node_label: str = "NaisTenant"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("NAIS_TENANT_ID", set_in_kwargs=True)},
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "RESOURCE"
    properties: NaisDeploymentToTenantRelProperties = (
        NaisDeploymentToTenantRelProperties()
    )


@dataclass(frozen=True)
class NaisDeploymentToTeamRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisTeam)-[:HAS_DEPLOYMENT]->(:NaisDeployment)
class NaisDeploymentToTeamRel(CartographyRelSchema):
    target_node_label: str = "NaisTeam"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"slug": PropertyRef("team_slug")},
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "HAS_DEPLOYMENT"
    properties: NaisDeploymentToTeamRelProperties = NaisDeploymentToTeamRelProperties()


@dataclass(frozen=True)
class NaisDeploymentToAppRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisApp)-[:HAS_DEPLOYMENT]->(:NaisDeployment)
class NaisDeploymentToAppRel(CartographyRelSchema):
    target_node_label: str = "NaisApp"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("app_id")},
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "HAS_DEPLOYMENT"
    properties: NaisDeploymentToAppRelProperties = NaisDeploymentToAppRelProperties()


@dataclass(frozen=True)
class NaisDeploymentToGitHubRepoRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisDeployment)-[:DEPLOYED_FROM]->(:GitHubRepository)
# Matched via deployment.repository_url = "https://github.com/navikt/my-app" against GitHubRepository.id
class NaisDeploymentToGitHubRepoRel(CartographyRelSchema):
    target_node_label: str = "GitHubRepository"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("repository_url")},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "DEPLOYED_FROM"
    properties: NaisDeploymentToGitHubRepoRelProperties = (
        NaisDeploymentToGitHubRepoRelProperties()
    )


@dataclass(frozen=True)
class NaisDeploymentSchema(CartographyNodeSchema):
    label: str = "NaisDeployment"
    properties: NaisDeploymentNodeProperties = NaisDeploymentNodeProperties()
    sub_resource_relationship: NaisDeploymentToTenantRel = NaisDeploymentToTenantRel()
    other_relationships: OtherRelationships = OtherRelationships(
        [
            NaisDeploymentToTeamRel(),
            NaisDeploymentToAppRel(),
            NaisDeploymentToGitHubRepoRel(),
        ]
    )


# ---------------------------------------------------------------------------
# NaisDeploymentToGitHubUserRel (MatchLink)
# Links NaisDeployment to the GitHubUser who triggered it via deployerUsername.
# Silently skips if the GitHubUser node does not exist (bot accounts, external
# contributors not in the GitHub org, or GitHub module not yet synced).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NaisDeploymentToGitHubUserRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)
    _sub_resource_label: PropertyRef = PropertyRef(
        "_sub_resource_label", set_in_kwargs=True
    )
    _sub_resource_id: PropertyRef = PropertyRef("_sub_resource_id", set_in_kwargs=True)


@dataclass(frozen=True)
# (:GitHubUser)-[:TRIGGERED_BY]->(:NaisDeployment)
# Matched via GitHubUser.username == NaisDeployment.deployer_username
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
    properties: NaisDeploymentToGitHubUserRelProperties = (
        NaisDeploymentToGitHubUserRelProperties()
    )

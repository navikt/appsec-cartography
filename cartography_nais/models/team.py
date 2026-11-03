from dataclasses import dataclass

from cartography.models.core.common import PropertyRef
from cartography.models.core.nodes import CartographyNodeProperties
from cartography.models.core.nodes import CartographyNodeSchema
from cartography.models.core.nodes import ExtraNodeLabel
from cartography.models.core.nodes import ExtraNodeLabels
from cartography.models.core.relationships import CartographyRelProperties
from cartography.models.core.relationships import CartographyRelSchema
from cartography.models.core.relationships import LinkDirection
from cartography.models.core.relationships import make_source_node_matcher
from cartography.models.core.relationships import make_target_node_matcher
from cartography.models.core.relationships import OtherRelationships
from cartography.models.core.relationships import SourceNodeMatcher
from cartography.models.core.relationships import TargetNodeMatcher


@dataclass(frozen=True)
class NaisRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
class NaisMatchLinkRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)
    _sub_resource_label: PropertyRef = PropertyRef(
        "_sub_resource_label", set_in_kwargs=True
    )
    _sub_resource_id: PropertyRef = PropertyRef("_sub_resource_id", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisTenant)-[:RESOURCE]->(:Nais*)
class NaisTenantRel(CartographyRelSchema):
    target_node_label: str = "NaisTenant"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("NAIS_TENANT_ID", set_in_kwargs=True)},
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "RESOURCE"
    properties: NaisRelProperties = NaisRelProperties()


# ---------------------------------------------------------------------------
# NaisTeam
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NaisTeamNodeProperties(CartographyNodeProperties):
    id: PropertyRef = PropertyRef("id")
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)
    slug: PropertyRef = PropertyRef("slug", extra_index=True)
    purpose: PropertyRef = PropertyRef("purpose")
    slack_channel: PropertyRef = PropertyRef("slack_channel")
    last_successful_sync: PropertyRef = PropertyRef("last_successful_sync")
    deletion_in_progress: PropertyRef = PropertyRef("deletion_in_progress")
    entra_group_id: PropertyRef = PropertyRef("entra_group_id")
    github_team_slug: PropertyRef = PropertyRef("github_team_slug")
    google_group_email: PropertyRef = PropertyRef("google_group_email")
    google_artifact_registry: PropertyRef = PropertyRef("google_artifact_registry")


@dataclass(frozen=True)
# (:NaisTeam)-[:HAS_ENTRA_GROUP]->(:EntraGroup)
class NaisTeamToEntraGroupRel(CartographyRelSchema):
    target_node_label: str = "EntraGroup"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("entra_group_id")},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "HAS_ENTRA_GROUP"
    properties: NaisRelProperties = NaisRelProperties()


@dataclass(frozen=True)
# (:NaisTeam)-[:HAS_GITHUB_TEAM]->(:GitHubTeam)
class NaisTeamToGitHubTeamRel(CartographyRelSchema):
    target_node_label: str = "GitHubTeam"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"name": PropertyRef("github_team_slug")},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "HAS_GITHUB_TEAM"
    properties: NaisRelProperties = NaisRelProperties()


@dataclass(frozen=True)
# (:NaisTeam)-[:HAS_GOOGLE_GROUP]->(:GoogleWorkspaceGroup)
class NaisTeamToGoogleGroupRel(CartographyRelSchema):
    target_node_label: str = "GoogleWorkspaceGroup"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"email": PropertyRef("google_group_email")},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "HAS_GOOGLE_GROUP"
    properties: NaisRelProperties = NaisRelProperties()


@dataclass(frozen=True)
class NaisTeamSchema(CartographyNodeSchema):
    label: str = "NaisTeam"
    properties: NaisTeamNodeProperties = NaisTeamNodeProperties()
    sub_resource_relationship: NaisTenantRel = NaisTenantRel()
    other_relationships: OtherRelationships = OtherRelationships(
        [
            NaisTeamToEntraGroupRel(),
            NaisTeamToGitHubTeamRel(),
            NaisTeamToGoogleGroupRel(),
        ]
    )


# ---------------------------------------------------------------------------
# NaisTeamEnvironment: a team's footprint in one environment (cluster)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NaisTeamEnvironmentNodeProperties(CartographyNodeProperties):
    id: PropertyRef = PropertyRef("id")
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)
    team_slug: PropertyRef = PropertyRef("team_slug", extra_index=True)
    environment: PropertyRef = PropertyRef("environment", extra_index=True)
    gcp_project_id: PropertyRef = PropertyRef("gcp_project_id")


@dataclass(frozen=True)
# (:NaisTeam)-[:HAS_ENVIRONMENT]->(:NaisTeamEnvironment)
class NaisTeamEnvironmentToTeamRel(CartographyRelSchema):
    target_node_label: str = "NaisTeam"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("team_id")},
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "HAS_ENVIRONMENT"
    properties: NaisRelProperties = NaisRelProperties()


@dataclass(frozen=True)
# (:NaisTeamEnvironment)-[:HAS_NAMESPACE]->(:KubernetesNamespace)
# Nais environment names are the Kubernetes cluster names; namespaces are team slugs.
class NaisTeamEnvironmentToNamespaceRel(CartographyRelSchema):
    target_node_label: str = "KubernetesNamespace"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {
            "cluster_name": PropertyRef("environment"),
            "name": PropertyRef("team_slug"),
        },
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "HAS_NAMESPACE"
    properties: NaisRelProperties = NaisRelProperties()


@dataclass(frozen=True)
# (:NaisTeamEnvironment)-[:HAS_GCP_PROJECT]->(:GCPProject)
class NaisTeamEnvironmentToGCPProjectRel(CartographyRelSchema):
    target_node_label: str = "GCPProject"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("gcp_project_id")},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "HAS_GCP_PROJECT"
    properties: NaisRelProperties = NaisRelProperties()


@dataclass(frozen=True)
class NaisTeamEnvironmentSchema(CartographyNodeSchema):
    label: str = "NaisTeamEnvironment"
    properties: NaisTeamEnvironmentNodeProperties = NaisTeamEnvironmentNodeProperties()
    sub_resource_relationship: NaisTenantRel = NaisTenantRel()
    other_relationships: OtherRelationships = OtherRelationships(
        [
            NaisTeamEnvironmentToTeamRel(),
            NaisTeamEnvironmentToNamespaceRel(),
            NaisTeamEnvironmentToGCPProjectRel(),
        ]
    )


# ---------------------------------------------------------------------------
# NaisMember
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NaisMemberNodeProperties(CartographyNodeProperties):
    id: PropertyRef = PropertyRef("id")
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)
    # The nav.no address identifies the same person across all modules.
    email: PropertyRef = PropertyRef("email", extra_index=True)
    normalized_email: PropertyRef = PropertyRef("normalized_email", extra_index=True)
    name: PropertyRef = PropertyRef("name")
    external_id: PropertyRef = PropertyRef("external_id")
    is_admin: PropertyRef = PropertyRef("is_admin")


@dataclass(frozen=True)
class NaisMemberSchema(CartographyNodeSchema):
    label: str = "NaisMember"
    properties: NaisMemberNodeProperties = NaisMemberNodeProperties()
    sub_resource_relationship: NaisTenantRel = NaisTenantRel()
    # UserAccount label is used for ontology mapping
    extra_node_labels: ExtraNodeLabels = ExtraNodeLabels(
        [ExtraNodeLabel("UserAccount", "Nais team member account")]
    )


@dataclass(frozen=True)
class NaisTeamMembershipRelProperties(NaisMatchLinkRelProperties):
    role: PropertyRef = PropertyRef("role")


@dataclass(frozen=True)
# (:NaisTeam)-[:HAS_MEMBER {role}]->(:NaisMember)
class NaisTeamMembershipMatchLink(CartographyRelSchema):
    target_node_label: str = "NaisMember"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("member_id")},
    )
    source_node_label: str = "NaisTeam"
    source_node_matcher: SourceNodeMatcher = make_source_node_matcher(
        {"id": PropertyRef("team_id")},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "HAS_MEMBER"
    properties: NaisTeamMembershipRelProperties = NaisTeamMembershipRelProperties()

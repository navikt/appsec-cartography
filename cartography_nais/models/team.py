from dataclasses import dataclass

from cartography.models.core.common import PropertyRef
from cartography.models.core.nodes import CartographyNodeProperties
from cartography.models.core.nodes import CartographyNodeSchema
from cartography.models.core.nodes import ExtraNodeLabel
from cartography.models.core.nodes import ExtraNodeLabels
from cartography.models.core.relationships import CartographyRelProperties
from cartography.models.core.relationships import CartographyRelSchema
from cartography.models.core.relationships import LinkDirection
from cartography.models.core.relationships import make_target_node_matcher
from cartography.models.core.relationships import OtherRelationships
from cartography.models.core.relationships import TargetNodeMatcher

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
    # External resource IDs stored for direct matching
    entra_group_id: PropertyRef = PropertyRef("entra_group_id")
    github_team_slug: PropertyRef = PropertyRef("github_team_slug")
    google_group_email: PropertyRef = PropertyRef("google_group_email")


@dataclass(frozen=True)
class NaisTeamToTenantRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisTeam)<-[:RESOURCE]-(:NaisTenant)
class NaisTeamToTenantRel(CartographyRelSchema):
    target_node_label: str = "NaisTenant"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("NAIS_TENANT_ID", set_in_kwargs=True)},
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "RESOURCE"
    properties: NaisTeamToTenantRelProperties = NaisTeamToTenantRelProperties()


@dataclass(frozen=True)
class NaisTeamToEntraGroupRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisTeam)-[:HAS_ENTRA_GROUP]->(:EntraGroup)
class NaisTeamToEntraGroupRel(CartographyRelSchema):
    target_node_label: str = "EntraGroup"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("entra_group_id")},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "HAS_ENTRA_GROUP"
    properties: NaisTeamToEntraGroupRelProperties = NaisTeamToEntraGroupRelProperties()


@dataclass(frozen=True)
class NaisTeamToGitHubTeamRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisTeam)-[:HAS_GITHUB_TEAM]->(:GitHubTeam)
class NaisTeamToGitHubTeamRel(CartographyRelSchema):
    target_node_label: str = "GitHubTeam"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"name": PropertyRef("github_team_slug")},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "HAS_GITHUB_TEAM"
    properties: NaisTeamToGitHubTeamRelProperties = NaisTeamToGitHubTeamRelProperties()


@dataclass(frozen=True)
class NaisTeamSchema(CartographyNodeSchema):
    label: str = "NaisTeam"
    properties: NaisTeamNodeProperties = NaisTeamNodeProperties()
    sub_resource_relationship: NaisTeamToTenantRel = NaisTeamToTenantRel()
    other_relationships: OtherRelationships = OtherRelationships(
        [
            NaisTeamToEntraGroupRel(),
            NaisTeamToGitHubTeamRel(),
        ]
    )


# ---------------------------------------------------------------------------
# NaisMember
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NaisMemberNodeProperties(CartographyNodeProperties):
    id: PropertyRef = PropertyRef("id")
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)
    email: PropertyRef = PropertyRef("email", extra_index=True)
    name: PropertyRef = PropertyRef("name")
    external_id: PropertyRef = PropertyRef("external_id")


@dataclass(frozen=True)
class NaisMemberToTenantRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
# (:NaisMember)<-[:RESOURCE]-(:NaisTenant)
class NaisMemberToTenantRel(CartographyRelSchema):
    target_node_label: str = "NaisTenant"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("NAIS_TENANT_ID", set_in_kwargs=True)},
    )
    direction: LinkDirection = LinkDirection.INWARD
    rel_label: str = "RESOURCE"
    properties: NaisMemberToTenantRelProperties = NaisMemberToTenantRelProperties()


@dataclass(frozen=True)
class NaisMemberToTeamRelProperties(CartographyRelProperties):
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)
    role: PropertyRef = PropertyRef("role")


@dataclass(frozen=True)
# (:NaisTeam)-[:HAS_MEMBER]->(:NaisMember)
class NaisTeamToMemberRel(CartographyRelSchema):
    target_node_label: str = "NaisMember"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("member_ids", one_to_many=True)},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "HAS_MEMBER"
    properties: NaisMemberToTeamRelProperties = NaisMemberToTeamRelProperties()


@dataclass(frozen=True)
class NaisMemberSchema(CartographyNodeSchema):
    label: str = "NaisMember"
    properties: NaisMemberNodeProperties = NaisMemberNodeProperties()
    sub_resource_relationship: NaisMemberToTenantRel = NaisMemberToTenantRel()
    extra_node_labels: ExtraNodeLabels = ExtraNodeLabels(
        [ExtraNodeLabel("UserAccount", "Nais team member account")]
    )  # UserAccount label is used for ontology mapping

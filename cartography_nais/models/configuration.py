from dataclasses import dataclass

from cartography.models.core.common import PropertyRef
from cartography.models.core.nodes import CartographyNodeProperties
from cartography.models.core.nodes import CartographyNodeSchema
from cartography.models.core.relationships import CartographyRelSchema
from cartography.models.core.relationships import LinkDirection
from cartography.models.core.relationships import make_target_node_matcher
from cartography.models.core.relationships import OtherRelationships
from cartography.models.core.relationships import TargetNodeMatcher
from cartography_nais.models.team import NaisRelProperties
from cartography_nais.models.team import NaisTenantRel

# Metadata only: secret values and config values are never fetched.


@dataclass(frozen=True)
class NaisConfigurationNodeProperties(CartographyNodeProperties):
    id: PropertyRef = PropertyRef("id")
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)
    name: PropertyRef = PropertyRef("name", extra_index=True)
    team_slug: PropertyRef = PropertyRef("team_slug", extra_index=True)
    environment: PropertyRef = PropertyRef("environment")
    keys: PropertyRef = PropertyRef("keys")
    last_modified_at: PropertyRef = PropertyRef("last_modified_at")


@dataclass(frozen=True)
class _ToTeamEnvironmentRel(CartographyRelSchema):
    target_node_label: str = "NaisTeamEnvironment"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("team_environment_id")},
    )
    direction: LinkDirection = LinkDirection.INWARD
    properties: NaisRelProperties = NaisRelProperties()


@dataclass(frozen=True)
class _ToAppRel(CartographyRelSchema):
    target_node_label: str = "NaisApp"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("workload_ids", one_to_many=True)},
    )
    direction: LinkDirection = LinkDirection.INWARD
    properties: NaisRelProperties = NaisRelProperties()


@dataclass(frozen=True)
# (:Nais{Secret,Config})-[:LAST_MODIFIED_BY]->(:NaisMember)
class NaisConfigurationToMemberRel(CartographyRelSchema):
    target_node_label: str = "NaisMember"
    target_node_matcher: TargetNodeMatcher = make_target_node_matcher(
        {"id": PropertyRef("last_modified_by_id")},
    )
    direction: LinkDirection = LinkDirection.OUTWARD
    rel_label: str = "LAST_MODIFIED_BY"
    properties: NaisRelProperties = NaisRelProperties()


@dataclass(frozen=True)
# (:NaisTeamEnvironment)-[:HAS_SECRET]->(:NaisSecret)
class NaisSecretToTeamEnvironmentRel(_ToTeamEnvironmentRel):
    rel_label: str = "HAS_SECRET"


@dataclass(frozen=True)
# (:NaisApp)-[:USES_SECRET]->(:NaisSecret)
class NaisSecretToAppRel(_ToAppRel):
    rel_label: str = "USES_SECRET"


@dataclass(frozen=True)
class NaisSecretSchema(CartographyNodeSchema):
    label: str = "NaisSecret"
    properties: NaisConfigurationNodeProperties = NaisConfigurationNodeProperties()
    sub_resource_relationship: NaisTenantRel = NaisTenantRel()
    other_relationships: OtherRelationships = OtherRelationships(
        [
            NaisSecretToTeamEnvironmentRel(),
            NaisSecretToAppRel(),
            NaisConfigurationToMemberRel(),
        ]
    )


@dataclass(frozen=True)
# (:NaisTeamEnvironment)-[:HAS_CONFIG]->(:NaisConfig)
class NaisConfigToTeamEnvironmentRel(_ToTeamEnvironmentRel):
    rel_label: str = "HAS_CONFIG"


@dataclass(frozen=True)
# (:NaisApp)-[:USES_CONFIG]->(:NaisConfig)
class NaisConfigToAppRel(_ToAppRel):
    rel_label: str = "USES_CONFIG"


@dataclass(frozen=True)
class NaisConfigSchema(CartographyNodeSchema):
    label: str = "NaisConfig"
    properties: NaisConfigurationNodeProperties = NaisConfigurationNodeProperties()
    sub_resource_relationship: NaisTenantRel = NaisTenantRel()
    other_relationships: OtherRelationships = OtherRelationships(
        [
            NaisConfigToTeamEnvironmentRel(),
            NaisConfigToAppRel(),
            NaisConfigurationToMemberRel(),
        ]
    )


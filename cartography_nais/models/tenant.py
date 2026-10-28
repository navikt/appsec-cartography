from dataclasses import dataclass

from cartography.models.core.common import PropertyRef
from cartography.models.core.nodes import CartographyNodeProperties
from cartography.models.core.nodes import CartographyNodeSchema
from cartography.models.core.nodes import ExtraNodeLabel
from cartography.models.core.nodes import ExtraNodeLabels


@dataclass(frozen=True)
class NaisTenantNodeProperties(CartographyNodeProperties):
    id: PropertyRef = PropertyRef("id")
    lastupdated: PropertyRef = PropertyRef("lastupdated", set_in_kwargs=True)


@dataclass(frozen=True)
class NaisTenantSchema(CartographyNodeSchema):
    label: str = "NaisTenant"
    properties: NaisTenantNodeProperties = NaisTenantNodeProperties()
    sub_resource_relationship = None
    extra_node_labels: ExtraNodeLabels = ExtraNodeLabels(
        [ExtraNodeLabel("Tenant", "Nais API tenant")]
    )

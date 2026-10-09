"""图谱抽取的实体/事件数据模型与抽取提示词装配。"""

from pydantic import BaseModel, Field


class Event(BaseModel):
    """A notable occurrence, update, report, incident, or planned activity."""

    event_type: str | None = Field(None, description="High-level event type.")
    status: str | None = Field(None, description="Current known event state.")
    event_note: str | None = Field(None, description="Short factual event note.")


class Organization(BaseModel):
    """A company, agency, institution, or other organized body."""

    organization_type: str | None = Field(
        None,
        description="Type or role of the organization.",
    )
    jurisdiction: str | None = Field(
        None,
        description="Geographic or operational scope when available.",
    )


class Person(BaseModel):
    """An individual actor, source, representative, or affected party."""

    role: str | None = Field(None, description="Person role in the event.")
    affiliation: str | None = Field(None, description="Known affiliation.")


class Location(BaseModel):
    """A physical, administrative, or virtual location relevant to the event."""

    location_type: str | None = Field(
        None,
        description="Site, city, region, facility, online space, or location type.",
    )
    region: str | None = Field(None, description="Broader region when available.")


class Topic(BaseModel):
    """A theme, issue, program, claim, concern, or subject in the event."""

    topic_area: str | None = Field(None, description="General topic area.")
    stance: str | None = Field(
        None,
        description="Reported position or concern when available.",
    )


class Product(BaseModel):
    """A product, service, tool, platform, asset, or system in the event."""

    product_type: str | None = Field(None, description="General product type.")
    operator: str | None = Field(
        None,
        description="Responsible organization when available.",
    )


class Involves(BaseModel):
    """Connects an event to a participant, object, topic, or affected entity."""

    role: str | None = Field(None, description="How the target is involved.")


class OccursAt(BaseModel):
    """Connects an event to a relevant location."""

    timing: str | None = Field(
        None,
        description="Reported timing or period when available.",
    )


class Affects(BaseModel):
    """Connects an event to an impacted person, group, organization, or topic."""

    impact: str | None = Field(None, description="Nature of the reported impact.")


class Mentions(BaseModel):
    """Connects an event or actor to a referenced topic, person, or organization."""

    context: str | None = Field(None, description="Why the target was mentioned.")


class Causes(BaseModel):
    """Connects a source event, action, or condition to a resulting impact."""

    basis: str | None = Field(None, description="Evidence for the causal relation.")


ENTITY_TYPES = {
    "Event": Event,
    "Organization": Organization,
    "Person": Person,
    "Location": Location,
    "Topic": Topic,
    "Product": Product,
}

EDGE_TYPES = {
    "Involves": Involves,
    "OccursAt": OccursAt,
    "Affects": Affects,
    "Mentions": Mentions,
    "Causes": Causes,
}

EDGE_TYPE_MAP = {
    ("Event", "Organization"): ["Involves", "Affects", "Mentions"],
    ("Event", "Person"): ["Involves", "Affects", "Mentions"],
    ("Event", "Location"): ["OccursAt", "Affects", "Mentions"],
    ("Event", "Topic"): ["Involves", "Affects", "Mentions", "Causes"],
    ("Event", "Product"): ["Involves", "Affects", "Mentions"],
    ("Organization", "Organization"): ["Involves", "Affects", "Mentions"],
    ("Person", "Organization"): ["Involves", "Mentions"],
    ("Topic", "Topic"): ["Causes", "Mentions"],
    ("Entity", "Entity"): list(EDGE_TYPES),
}

"""Phase 0 versioned transport models; not a full node/event catalog."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    FiniteFloat,
    PlainSerializer,
    StringConstraints,
    WithJsonSchema,
    model_validator,
)

from autoaxe.domain.canonical import canonical_sha256
from autoaxe.domain.types import Mode, decimal_string, utc_datetime, utc_string

Identifier = Annotated[str, StringConstraints(min_length=1, max_length=128)]
Money = Annotated[
    str,
    BeforeValidator(decimal_string),
    WithJsonSchema({"type": "string", "pattern": r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?$"}),
]
UtcTime = Annotated[
    datetime,
    AfterValidator(utc_datetime),
    PlainSerializer(utc_string, return_type=str, when_used="json"),
    WithJsonSchema(
        {"type": "string", "format": "date-time", "pattern": "Z$"}, mode="serialization"
    ),
]
SafeInt = Annotated[int, Field(strict=True, ge=0, le=9007199254740991)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class Meta(Contract):
    request_id: Identifier
    schema_version: Literal[1] = 1
    source: Literal["synthetic_fixture"] = "synthetic_fixture"
    permission: Literal["fixture_only"] = "fixture_only"


class ErrorDetail(Contract):
    code: Identifier
    message: str
    reason: str
    retryable: bool = False
    request_id: Identifier


class ErrorEnvelope(Contract):
    error: ErrorDetail


class Health(Contract):
    status: Literal["ok"] = "ok"
    environment: Literal["fixture"] = "fixture"
    live_enabled: Literal[False] = False
    external_mcp_enabled: Literal[False] = False


class HealthResponse(Contract):
    data: Health
    meta: Meta


class Quote(Contract):
    series_id: Identifier
    value: Money | None
    unit: Literal["USD"]
    source_event_at: UtcTime | None
    quality: Literal["fixture", "no_data"]

    @model_validator(mode="after")
    def coherent_quality(self) -> "Quote":
        if self.quality == "no_data" and (
            self.value is not None or self.source_event_at is not None
        ):
            raise ValueError("missing observation must have null value and source time")
        if self.quality == "fixture" and (self.value is None or self.source_event_at is None):
            raise ValueError("fixture observation requires value and source time")
        return self


class QuoteResponse(Contract):
    data: Quote
    meta: Meta


class FixturePageMeta(Meta):
    next_cursor: str | None = None


class QuotePage(Contract):
    data: list[Quote]
    meta: FixturePageMeta


class FixtureChange(Contract):
    expected_version: SafeInt
    label: Identifier


class FixtureMutation(Contract):
    resource_id: Literal["fixture"]
    version: SafeInt
    label: Identifier


class MutationResponse(Contract):
    data: FixtureMutation
    meta: Meta


class ResetPolicy(Contract):
    business_days: Annotated[int, Field(strict=True, gt=0)]
    calendar_id: Identifier
    calendar_version: Identifier
    timezone: Identifier


class IndicatorConfig(Contract):
    indicator_id: Identifier
    operator: Literal["LTE", "GTE"]
    threshold: FiniteFloat
    freshness_seconds: Annotated[int, Field(strict=True, gt=0)]


class IndicatorNode(Contract):
    node_id: Identifier
    node_type: Literal["indicator"]
    node_schema_version: Literal[1]
    config: IndicatorConfig


class EmptyConfig(Contract):
    pass


class ResultNode(Contract):
    node_id: Identifier
    node_type: Literal["condition_result"]
    node_schema_version: Literal[1]
    config: EmptyConfig


Node = Annotated[IndicatorNode | ResultNode, Field(discriminator="node_type")]


class Edge(Contract):
    edge_id: Identifier
    source_node_id: Identifier
    source_port: Literal["result"]
    target_node_id: Identifier
    target_port: Literal["condition"]


class Position(Contract):
    x: FiniteFloat
    y: FiniteFloat


class Presentation(Contract):
    presentation_version: Literal[1] = 1
    positions: dict[str, Position] = Field(default_factory=dict)


class ExecutionPolicy(Contract):
    fixture_only: Literal[True] = True


class Workflow(Contract):
    schema_version: Literal[1]
    workflow_id: Identifier
    workflow_version: Annotated[int, Field(strict=True, gt=0, le=9007199254740991)]
    name: Identifier
    mode: Mode
    priority: SafeInt
    reset_policy: ResetPolicy
    execution_policy: ExecutionPolicy
    risk_profile_ref: Identifier
    dependency_refs: list[Identifier]
    nodes: Annotated[list[Node], Field(min_length=1, max_length=100)]
    edges: Annotated[list[Edge], Field(max_length=100)]
    presentation: Presentation | None = None

    @model_validator(mode="after")
    def graph_fixture_validation(self) -> "Workflow":
        ids = {n.node_id: n for n in self.nodes}
        if len(ids) != len(self.nodes) or len({e.edge_id for e in self.edges}) != len(self.edges):
            raise ValueError("duplicate node or edge id")
        seen_targets: set[str] = set()
        for edge in self.edges:
            source, target = ids.get(edge.source_node_id), ids.get(edge.target_node_id)
            if not isinstance(source, IndicatorNode) or not isinstance(target, ResultNode):
                raise ValueError("invalid fixture port or node reference")
            if target.node_id in seen_targets:
                raise ValueError("duplicate input")
            seen_targets.add(target.node_id)
        if {n.node_id for n in self.nodes if isinstance(n, ResultNode)} != seen_targets:
            raise ValueError("result input missing")
        return self

    def approval_hash(self) -> str:
        return canonical_sha256(self.model_dump(mode="json", exclude={"presentation"}))


class PricePayload(Contract):
    symbol: Identifier
    price: Money
    currency: Literal["USD", "USDT"]


class PriceEvent(Contract):
    event_id: Identifier
    event_type: Literal["market.price.updated"]
    schema_version: Literal[1]
    origin_db: Literal["autoaxe_market"]
    aggregate_type: Literal["market_series"]
    aggregate_id: Identifier
    aggregate_version: SafeInt
    source: Identifier
    series_id: Identifier
    source_event_at: UtcTime | None
    occurred_at: UtcTime
    available_at: UtcTime
    committed_at: UtcTime
    correlation_id: Identifier
    causation_id: Identifier | None
    mode: None
    account_ref: None
    payload: PricePayload


class JobPayload(Contract):
    job_id: Identifier
    status: Literal["queued", "running", "failed", "succeeded", "cancel_requested", "cancelled"]


class JobEvent(Contract):
    event_id: Identifier
    event_type: Literal["job.status.changed"]
    schema_version: Literal[1]
    origin_db: Literal[
        "autoaxe_app",
        "autoaxe_market",
        "autoaxe_dev",
        "autoaxe_test",
        "autoaxe_backtest",
        "autoaxe_dry_run",
        "autoaxe_paper_local",
        "autoaxe_paper_broker",
        "autoaxe_live",
    ]
    aggregate_type: Literal["job"]
    aggregate_id: Identifier
    aggregate_version: SafeInt
    source: None
    series_id: None
    source_event_at: None
    occurred_at: UtcTime
    available_at: UtcTime
    committed_at: UtcTime
    correlation_id: Identifier
    causation_id: Identifier | None
    mode: None
    account_ref: None
    payload: JobPayload


class ObservationPayload(Contract):
    observation_id: Identifier
    revision: SafeInt
    quality: Identifier


class ObservationEvent(Contract):
    event_id: Identifier
    event_type: Literal["market.observation.recorded"]
    schema_version: Literal[1]
    origin_db: Literal["autoaxe_market", "autoaxe_dev", "autoaxe_test"]
    aggregate_type: Literal["market_series"]
    aggregate_id: Identifier
    aggregate_version: SafeInt
    source: Identifier
    series_id: Identifier
    source_event_at: UtcTime | None
    occurred_at: UtcTime
    available_at: UtcTime
    committed_at: UtcTime
    correlation_id: Identifier
    causation_id: Identifier | None
    mode: None
    account_ref: None
    payload: ObservationPayload


Event = Annotated[PriceEvent | JobEvent | ObservationEvent, Field(discriminator="event_type")]

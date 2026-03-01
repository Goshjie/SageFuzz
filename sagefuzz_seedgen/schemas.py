from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class UserIntent(BaseModel):
    """User-provided intent for this run.

    This system is intent-driven. The user intent must describe:
    - what feature/functionality to test
    - how to interpret the topology (e.g. which host is internal/external)
    """

    feature_under_test: str = Field(..., description="What functionality to test, in user terms.")
    intent_text: str = Field(..., description="Natural language description of the test intent.")
    topology_zone_mapping: Optional[str] = Field(
        None,
        description=(
            "Intent-level topology/zone mapping description, e.g. which hosts belong to which zone "
            "(internal/external/DMZ) and who is allowed to initiate vs. only reply."
        ),
    )
    role_policy: Optional[str] = Field(
        None,
        description=(
            "Natural-language policy for communication roles, e.g. initiator/responder constraints "
            "or directionality expectations."
        ),
    )
    preferred_role_bindings: Optional[Dict[str, str]] = Field(
        None,
        description="Optional role->host preference map, e.g. {'initiator':'h2','responder':'h3'}.",
    )
    include_negative_case: Optional[bool] = Field(
        None, description="Whether to include one negative scenario in generated packet sequence."
    )


class UserQuestion(BaseModel):
    """A question that Agent1 asks the user, tied to a specific intent field."""

    field: Literal[
        "feature_under_test",
        "intent_text",
        "topology_zone_mapping",
        "role_policy",
        "preferred_role_bindings",
        "include_negative_case",
    ]
    question_zh: str = Field(..., description="Question to the user in Simplified Chinese.")
    required: bool = True
    expected_format: Optional[str] = Field(
        None, description="Optional hint, e.g. 'h1' or 'true/false' or 'h1,h2 internal; h3,h4 external'."
    )


class TaskSpec(BaseModel):
    """High-level packet generation task produced by Semantic Analyzer.

    Note: this is intentionally small; the agent is expected to query tools for evidence.
    """

    task_id: str = Field(..., description="Stable id for this task.")
    task_description: str = Field(..., description="Human readable intent.")
    feature_under_test: str = Field(..., description="What functionality to test (carried from user intent).")
    role_bindings: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Concrete role-to-host binding used for packet generation/validation, "
            "e.g. {'initiator':'h2','responder':'h3'}."
        ),
    )
    sequence_contract: List["SequenceScenarioSpec"] = Field(
        default_factory=list,
        description="Scenario contracts that define required packet steps and field relations.",
    )
    require_positive_and_negative: bool = Field(
        True,
        description="If true, sequence_contract must include and generate both required positive and negative scenarios.",
    )


class PacketStepSpec(BaseModel):
    tx_role: str = Field(..., description="Sender role for this step, must exist in task.role_bindings.")
    rx_role: Optional[str] = Field(
        None, description="Optional receiver role for this step, used for dst host/IP/MAC consistency checks."
    )
    protocol_stack: List[str] = Field(
        default_factory=list,
        description='Expected protocol stack for this step, e.g. ["Ethernet","IPv4","TCP"].',
    )
    field_expectations: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Expected packet fields. Value can be a literal (exact match) or an expectation object "
            "with keys such as equals/contains/not_contains/one_of."
        ),
    )


class FieldRelationSpec(BaseModel):
    left_step: int = Field(..., ge=1, description="1-based index into scenario steps.")
    left_field: str = Field(..., description="Field key on the left side, e.g. TCP.ack.")
    op: Literal["eq", "neq", "gt", "lt", "ge", "le"] = Field("eq")
    right_step: int = Field(..., ge=1, description="1-based index into scenario steps.")
    right_field: str = Field(..., description="Field key on the right side, e.g. TCP.seq.")
    right_delta: float = Field(
        0, description="Numeric delta added to right value before comparison, e.g. +1 for ack/seq continuity."
    )


class SequenceScenarioSpec(BaseModel):
    scenario: str = Field(..., description="Scenario tag in packet_sequence, e.g. positive_main / negative_case_1.")
    kind: Literal["positive", "negative", "neutral"] = Field(
        "neutral",
        description="Scenario kind used for high-level coverage checks.",
    )
    required: bool = Field(True, description="Whether this scenario must appear in packet_sequence.")
    steps: List[PacketStepSpec] = Field(
        default_factory=list,
        description="Ordered packet-step expectations for this scenario.",
    )
    field_relations: List[FieldRelationSpec] = Field(
        default_factory=list,
        description="Cross-step numeric field relations inside this scenario.",
    )
    allow_additional_packets: bool = Field(
        True, description="If false, packet count in this scenario must equal len(steps)."
    )


class PacketSpec(BaseModel):
    packet_id: int
    tx_host: str = Field(..., description="Which topology host sends this packet, e.g. h1/h3.")
    scenario: Optional[str] = Field(
        None, description="Optional tag (e.g. positive_handshake / negative_external_initiation)."
    )
    protocol_stack: List[str] = Field(..., description='E.g. ["Ethernet","IPv4","TCP"]')
    fields: Dict[str, Any] = Field(..., description="Flattened header fields.")


class CriticResult(BaseModel):
    status: Literal["PASS", "FAIL"]
    feedback: str


class PacketSequenceCandidate(BaseModel):
    task_id: str
    packet_sequence: List[PacketSpec]


class TableRule(BaseModel):
    table_name: str
    match_type: str = Field(..., description="Table key match type, e.g. exact/lpm/ternary.")
    match_keys: Dict[str, Any] = Field(
        default_factory=dict,
        description="Table match keys, e.g. {'hdr.ipv4.dstAddr': ['10.0.3.3', 32]}",
    )
    action_name: str
    action_data: Dict[str, Any] = Field(default_factory=dict, description="Action parameters keyed by parameter name.")
    priority: Optional[int] = None


class ControlPlaneOperation(BaseModel):
    order: int = Field(..., ge=1, description="1-based operation order within this testcase scenario.")
    operation_type: Literal[
        "apply_table_entry",
        "read_register",
        "write_register",
        "read_counter",
        "custom",
    ] = Field(..., description="Controller-side operation kind.")
    target: str = Field(..., description="Target object name, e.g. table/register/counter identifier.")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Operation parameters.")
    entity_index: Optional[int] = Field(
        None,
        ge=1,
        description=(
            "1-based index of related entities[] entry when operation_type=apply_table_entry. "
            "Null for non-entity operations."
        ),
    )
    expected_effect: Optional[str] = Field(
        None,
        description="Optional expected effect/observation for this operation.",
    )


class RuleSetCandidate(BaseModel):
    task_id: str
    entities: List[TableRule]
    control_plane_sequence: List[ControlPlaneOperation] = Field(
        default_factory=list,
        description="Ordered controller operations for this scenario.",
    )


class OraclePacketPrediction(BaseModel):
    packet_id: int
    expected_outcome: Literal["deliver", "drop", "unknown"]
    expected_rx_host: Optional[str] = None
    expected_rx_role: Optional[str] = None
    expected_observation: Optional[str] = None
    rationale: str


class OraclePredictionCandidate(BaseModel):
    task_id: str
    scenario: str
    packet_predictions: List[OraclePacketPrediction]
    assumptions: List[str] = Field(default_factory=list)


class RuntimePacketObservation(BaseModel):
    packet_id: int
    observed_outcome: Literal["deliver", "drop", "unknown"]
    observed_rx_host: Optional[str] = None
    observation_note: Optional[str] = None


class Agent1Output(BaseModel):
    """Semantic Analyzer output: either a TaskSpec, or questions for the user."""

    kind: Literal["task", "questions"]
    task: Optional[TaskSpec] = None
    questions: Optional[List[UserQuestion]] = None


class AttemptResult(BaseModel):
    task_id: str
    packet_sequence: List[PacketSpec]
    critic: CriticResult


class TopologySummary(BaseModel):
    hosts: Dict[str, Dict[str, Any]]
    links: List[List[str]]


class TestcaseOutput(BaseModel):
    program: str
    topology_ref: str
    topology: TopologySummary
    task_id: str
    packet_sequence: List[PacketSpec]
    entities: List[TableRule] = Field(default_factory=list)
    control_plane_sequence: List[ControlPlaneOperation] = Field(default_factory=list)
    oracle_prediction: Optional[OraclePredictionCandidate] = None
    oracle_comparison: Dict[str, Any] = Field(default_factory=dict)
    meta: Dict[str, Any] = Field(default_factory=dict)

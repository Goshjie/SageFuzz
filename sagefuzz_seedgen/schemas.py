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
    topology_mapping: Optional[str] = Field(
        None,
        description=(
            "Compatibility alias for topology description in non-zone scenarios "
            "(e.g., link-monitoring paths/subnets/VLAN grouping)."
        ),
    )
    role_policy: Optional[str] = Field(
        None,
        description=(
            "Natural-language policy for communication roles, e.g. initiator/responder constraints "
            "or directionality expectations."
        ),
    )
    observation_target: Optional[str] = Field(
        None,
        description=(
            "Optional observation target/resource for telemetry-style intents, e.g. a path, link, port, "
            "counter, register, or monitored flow."
        ),
    )
    observation_method: Optional[str] = Field(
        None,
        description=(
            "Optional observation method, e.g. controller reads register/counter after traffic or expects "
            "an in-band monitoring report."
        ),
    )
    expected_observation: Optional[str] = Field(
        None,
        description=(
            "Optional expected monitoring result, e.g. link utilization increases on the selected link, "
            "or a counter/register value changes after traffic."
        ),
    )
    traffic_pattern: Optional[str] = Field(
        None,
        description=(
            "Optional description of traffic stimulus intensity/pattern, e.g. repeated UDP packets, background "
            "flow plus probe packets, or a sustained stream between endpoints."
        ),
    )
    preferred_role_bindings: Optional[Dict[str, str]] = Field(
        None,
        description="Optional role->host preference map, e.g. {'initiator':'h2','responder':'h3'}.",
    )
    include_negative_case: Optional[bool] = Field(
        None, description="Whether to include one negative scenario in generated packet sequence."
    )
    test_objective: Optional[Literal["data_plane_behavior", "control_plane_rules"]] = Field(
        None,
        description=(
            "User-selected test objective. "
            "'data_plane_behavior' means generate packets+entities; "
            "'control_plane_rules' means packet-only generation (skip entity generation)."
        ),
    )


class UserQuestion(BaseModel):
    """A question that Agent1 asks the user, tied to a specific intent field."""

    field: Literal[
        "feature_under_test",
        "intent_text",
        "topology_zone_mapping",
        "topology_mapping",
        "role_policy",
        "observation_target",
        "observation_method",
        "expected_observation",
        "traffic_pattern",
        "preferred_role_bindings",
        "include_negative_case",
        "test_objective",
    ]
    question_zh: str = Field(..., description="Question to the user in Simplified Chinese.")
    required: bool = True
    expected_format: Optional[str] = Field(
        None, description="Optional hint, e.g. 'h1' or 'true/false' or 'h1,h2 internal; h3,h4 external'."
    )


class ObservationIntentSpec(BaseModel):
    order: int = Field(..., ge=1, description="1-based order of observation requirement within the task.")
    action_type: Literal["read_register", "read_counter", "read_meter", "custom"] = Field(
        ...,
        description="Observation action requested by the intent.",
    )
    target_hint: str = Field(
        ...,
        description="Program-level target hint, e.g. register/counter/link/path identifier or observation object.",
    )
    timing: Literal["before_traffic", "after_each_packet", "after_scenario", "custom"] = Field(
        "after_scenario",
        description="When the observation should happen relative to generated traffic.",
    )
    purpose: str = Field(..., description="Why this observation is needed for the test intent.")


class TaskSpec(BaseModel):
    """High-level packet generation task produced by Semantic Analyzer.

    Note: this is intentionally small; the agent is expected to query tools for evidence.
    """

    task_id: str = Field(..., description="Stable id for this task.")
    task_description: str = Field(..., description="Human readable intent.")
    feature_under_test: str = Field(..., description="What functionality to test (carried from user intent).")
    intent_category: Literal[
        "generic",
        "stateful_policy",
        "stateless_policy",
        "telemetry_monitoring",
        "state_observation",
        "path_validation",
        "forwarding_behavior",
        "load_distribution",
        "replication_multicast",
    ] = Field(
        "generic",
        description="High-level intent category inferred from user intent and tool evidence.",
    )
    observation_focus: Optional[str] = Field(
        None,
        description="What should be observed for telemetry/state-validation intents, e.g. a monitored link or counter.",
    )
    observation_method: Optional[str] = Field(
        None,
        description="How the observation is expected to be obtained, e.g. read_register/read_counter/controller check.",
    )
    expected_observation_semantics: Optional[str] = Field(
        None,
        description="Intent-level expected observation result, e.g. monitored link utilization increases after traffic.",
    )
    observation_requirements: List[ObservationIntentSpec] = Field(
        default_factory=list,
        description="Structured observation actions implied by the test intent.",
    )
    traffic_pattern: Optional[str] = Field(
        None,
        description="Traffic stimulus pattern needed to drive the intent, e.g. repeated probes or sustained flow.",
    )
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
    generation_mode: Literal["packet_and_entities", "packet_only"] = Field(
        "packet_and_entities",
        description=(
            "Execution mode for downstream generation. "
            "'packet_and_entities': run Agent4/5 and generate control-plane rules; "
            "'packet_only': skip Agent4/5 and generate only packet_sequence + oracle."
        ),
    )
    forbidden_tables: List[str] = Field(
        default_factory=list,
        description=(
            "Table names that entity generation must avoid. "
            "Supports full names (e.g., MyIngress.check_ports) and short names (e.g., check_ports)."
        ),
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
    repeat_count: int = Field(
        1,
        ge=1,
        description=(
            "How many packets should be generated for this logical step. Use values >1 for bursts or sustained traffic "
            "without enumerating every packet as a separate step."
        ),
    )
    traffic_profile: Optional[str] = Field(
        None,
        description=(
            "Optional traffic profile hint for this step, e.g. sustained_udp_stream, repeated_probe, or burst_traffic."
        ),
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
    scenario_goal: Optional[str] = Field(
        None,
        description="Intent-level goal of this scenario, e.g. establish state, drive counter growth, or verify drop.",
    )
    expected_observation: Optional[str] = Field(
        None,
        description="Scenario-level expected observation, especially for telemetry/monitoring tests.",
    )
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
        "read_meter",
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


class ExecutionOperation(BaseModel):
    order: int = Field(..., ge=1, description="1-based order in the unified scenario execution sequence.")
    operation_type: Literal[
        "send_packet",
        "apply_table_entry",
        "read_register",
        "write_register",
        "read_counter",
        "read_meter",
        "custom",
    ] = Field(..., description="Unified operation type spanning packet/control-plane actions.")
    packet_id: Optional[int] = Field(None, description="Referenced packet id for send_packet operations.")
    entity_index: Optional[int] = Field(None, ge=1, description="Referenced entities[] index for apply operations.")
    control_plane_order: Optional[int] = Field(
        None,
        ge=1,
        description="Referenced control_plane_sequence order for control-plane operations.",
    )
    target: Optional[str] = Field(None, description="Optional target resource name.")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Operation parameters.")
    expected_effect: Optional[str] = Field(None, description="Optional expected effect/observation.")


class RuleSetCandidate(BaseModel):
    task_id: str
    entities: List[TableRule]
    control_plane_sequence: List[ControlPlaneOperation] = Field(
        default_factory=list,
        description="Ordered controller operations for this scenario.",
    )
    execution_sequence: List[ExecutionOperation] = Field(
        default_factory=list,
        description="Unified ordered execution sequence across control-plane actions and packet sends.",
    )


class OraclePacketPrediction(BaseModel):
    packet_id: int
    sequence_order: int = Field(..., ge=1, description="1-based order of this packet in scenario prediction timeline.")
    expected_outcome: Literal["deliver", "drop", "unknown"]
    expected_rx_host: Optional[str] = None
    expected_rx_role: Optional[str] = None
    processing_decision: str = Field(..., description="How the switch is expected to process this packet.")
    expected_switch_state_before: str = Field(
        ...,
        description="Expected switch state snapshot/summary before this packet is processed.",
    )
    expected_switch_state_after: str = Field(
        ...,
        description="Expected switch state snapshot/summary after this packet is processed.",
    )
    matched_entity_index: Optional[int] = Field(
        None,
        ge=1,
        description="Optional 1-based entities[] index expected to handle this packet.",
    )
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
    execution_sequence: List[ExecutionOperation] = Field(default_factory=list)
    oracle_prediction: Optional[OraclePredictionCandidate] = None
    oracle_comparison: Dict[str, Any] = Field(default_factory=dict)
    meta: Dict[str, Any] = Field(default_factory=dict)

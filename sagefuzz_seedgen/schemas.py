from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def _normalize_operation_dict(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    out = dict(item)
    if "operation_type" not in out and isinstance(out.get("operation"), str):
        op = str(out.get("operation"))
        mapping = {"table_add": "apply_table_entry", "add_entry": "apply_table_entry"}
        out["operation_type"] = mapping.get(op, op)
    elif isinstance(out.get("operation_type"), str):
        mapping = {"table_add": "apply_table_entry", "add_entry": "apply_table_entry"}
        out["operation_type"] = mapping.get(out["operation_type"], out["operation_type"])
    if "order" not in out and isinstance(out.get("step"), int):
        out["order"] = out.get("step")
    entity_index = out.get("entity_index")
    if isinstance(entity_index, int) and entity_index <= 0:
        out["entity_index"] = None
    if out.get("parameters") is None:
        out["parameters"] = {}
    return out


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
    operator_constraints: Optional[str] = Field(
        None,
        description=(
            "Optional human/operator actions allowed or required before traffic, e.g. lower a threshold, fail a link, "
            "or notify a controller."
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
        "operator_constraints",
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


class OperatorActionSpec(BaseModel):
    order: int = Field(..., ge=1, description="1-based order of operator/manual action within the task.")
    action_type: Literal["manual_threshold_override", "manual_link_event", "manual_controller_notify", "custom"] = Field(
        ...,
        description="Type of operator/manual action required before or during testcase execution.",
    )
    timing: Literal["before_traffic", "between_scenarios", "after_traffic", "custom"] = Field(
        "before_traffic",
        description="When the operator action should occur.",
    )
    scenario: Optional[str] = Field(
        None,
        description="Optional scenario this action applies to. Null means task-wide.",
    )
    target: str = Field(..., description="Target resource or object, e.g. threshold, link, or controller command.")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parameters for the manual action.")
    expected_effect: Optional[str] = Field(None, description="What effect this action should have before packets are sent.")


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
    operator_actions: List[Any] = Field(
        default_factory=list,
        description="Ordered manual/operator actions needed before or during testcase execution.",
    )
    observation_requirements: List[Any] = Field(
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
    sequence_contract: List[Any] = Field(
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

    @field_validator("operator_actions")
    @classmethod
    def _validate_operator_actions(cls, value: List[Any]) -> List[OperatorActionSpec]:
        out: List[OperatorActionSpec] = []
        for item in value:
            try:
                out.append(item if isinstance(item, OperatorActionSpec) else OperatorActionSpec.model_validate(item))
            except Exception:
                continue
        return out

    @field_validator("observation_requirements")
    @classmethod
    def _validate_observation_requirements(cls, value: List[Any]) -> List[ObservationIntentSpec]:
        out: List[ObservationIntentSpec] = []
        for item in value:
            try:
                out.append(item if isinstance(item, ObservationIntentSpec) else ObservationIntentSpec.model_validate(item))
            except Exception:
                continue
        return out

    @field_validator("sequence_contract")
    @classmethod
    def _validate_sequence_contract(cls, value: List[Any]) -> List["SequenceScenarioSpec"]:
        out: List[SequenceScenarioSpec] = []
        for item in value:
            out.append(item if isinstance(item, SequenceScenarioSpec) else SequenceScenarioSpec.model_validate(item))
        return out


    @model_validator(mode="after")
    def _normalize_role_bindings(self) -> "TaskSpec":
        role_bindings = dict(self.role_bindings)
        if role_bindings and all(isinstance(k, str) and k.startswith("h") and k[1:].isdigit() for k in role_bindings.keys()):
            inverted = {str(v): str(k) for k, v in role_bindings.items() if isinstance(k, str) and isinstance(v, str)}
            if inverted and all(isinstance(host, str) and host.startswith("h") and host[1:].isdigit() for host in inverted.values()):
                self.role_bindings = inverted
                for scenario in self.sequence_contract:
                    if not isinstance(scenario, SequenceScenarioSpec):
                        continue
                    for step in scenario.steps:
                        if not isinstance(step, PacketStepSpec):
                            continue
                        if step.tx_role in role_bindings and isinstance(role_bindings.get(step.tx_role), str):
                            step.tx_role = str(role_bindings[step.tx_role])
                        if step.rx_role in role_bindings and isinstance(role_bindings.get(step.rx_role), str):
                            step.rx_role = str(role_bindings[step.rx_role])
        return self


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
    steps: List[Any] = Field(
        default_factory=list,
        description="Ordered packet-step expectations for this scenario.",
    )
    field_relations: List[Any] = Field(
        default_factory=list,
        description="Cross-step numeric field relations inside this scenario.",
    )
    allow_additional_packets: bool = Field(
        True, description="If false, packet count in this scenario must equal len(steps)."
    )

    @field_validator("kind", mode="before")
    @classmethod
    def _normalize_kind(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        token = value.strip().lower()
        mapping = {
            "required_positive": "positive",
            "positive_required": "positive",
            "required_negative": "negative",
            "negative_required": "negative",
        }
        return mapping.get(token, token)

    @field_validator("steps")
    @classmethod
    def _validate_steps(cls, value: List[Any]) -> List[PacketStepSpec]:
        return [item if isinstance(item, PacketStepSpec) else PacketStepSpec.model_validate(item) for item in value]

    @field_validator("field_relations")
    @classmethod
    def _validate_field_relations(cls, value: List[Any]) -> List[FieldRelationSpec]:
        out: List[FieldRelationSpec] = []
        for item in value:
            try:
                out.append(item if isinstance(item, FieldRelationSpec) else FieldRelationSpec.model_validate(item))
            except Exception:
                continue
        return out


class PacketSpec(BaseModel):
    packet_id: int
    tx_host: str = Field(..., description="Which topology host sends this packet, e.g. h1/h3.")
    scenario: Optional[str] = Field(
        None, description="Optional tag (e.g. positive_handshake / negative_external_initiation)."
    )
    protocol_stack: List[str] = Field(..., description='E.g. ["Ethernet","IPv4","TCP"]')
    fields: Dict[str, Any] = Field(..., description="Flattened header fields.")

    @model_validator(mode="after")
    def _normalize_field_aliases(self) -> "PacketSpec":
        aliases = {
            "IPv4.srcAddr": "IPv4.src",
            "IPv4.dstAddr": "IPv4.dst",
            "IPv4.protocol": "IPv4.proto",
            "IPv4.tos": "IPv4.diffserv",
            "TCP.srcPort": "TCP.sport",
            "TCP.dstPort": "TCP.dport",
            "TCP.seqNo": "TCP.seq",
            "TCP.ackNo": "TCP.ack",
            "TCP.res": "TCP.reserved",
            "UDP.srcPort": "UDP.sport",
            "UDP.dstPort": "UDP.dport",
            "UDP.length": "UDP.len",
        }
        normalized = dict(self.fields)
        for src, dst in aliases.items():
            if src in normalized and dst not in normalized:
                normalized[dst] = normalized[src]
        self.fields = normalized
        return self


class CriticResult(BaseModel):
    status: Literal["PASS", "FAIL"]
    feedback: str


class PacketSequenceCandidate(BaseModel):
    task_id: str
    packet_sequence: List[Any]

    @field_validator("packet_sequence")
    @classmethod
    def _validate_packet_sequence(cls, value: List[Any]) -> List[PacketSpec]:
        flattened: List[Any] = []
        next_packet_id = 1
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("packets"), list):
                scenario = item.get("scenario")
                for packet in item.get("packets", []):
                    if not isinstance(packet, dict):
                        continue
                    packet_copy = dict(packet)
                    packet_copy.setdefault("scenario", scenario)
                    packet_copy.setdefault("packet_id", next_packet_id)
                    flattened.append(packet_copy)
                    next_packet_id += 1
                continue
            if isinstance(item, dict) and isinstance(item.get("repeat_count"), int) and item.get("repeat_count", 1) > 1 and all(k in item for k in ("tx_host", "protocol_stack", "fields")):
                repeat_count = int(item.get("repeat_count", 1))
                scenario = item.get("scenario")
                base_fields = dict(item.get("fields", {})) if isinstance(item.get("fields", {}), dict) else {}
                for _ in range(repeat_count):
                    packet_copy = {
                        "packet_id": next_packet_id,
                        "tx_host": item.get("tx_host"),
                        "scenario": scenario,
                        "protocol_stack": item.get("protocol_stack"),
                        "fields": dict(base_fields),
                    }
                    flattened.append(packet_copy)
                    next_packet_id += 1
                continue
            if isinstance(item, PacketSpec):
                next_packet_id = max(next_packet_id, int(item.packet_id) + 1)
                flattened.append(item)
                continue
            if isinstance(item, dict):
                packet_copy = dict(item)
                packet_copy.setdefault("packet_id", next_packet_id)
                flattened.append(packet_copy)
                next_packet_id += 1
                continue
        return [item if isinstance(item, PacketSpec) else PacketSpec.model_validate(item) for item in flattened]


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
    entities: List[Any]
    control_plane_sequence: List[Any] = Field(
        default_factory=list,
        description="Ordered controller operations for this scenario.",
    )
    execution_sequence: List[Any] = Field(
        default_factory=list,
        description="Unified ordered execution sequence across control-plane actions and packet sends.",
    )

    @field_validator("entities")
    @classmethod
    def _validate_entities(cls, value: List[Any]) -> List[TableRule]:
        return [item if isinstance(item, TableRule) else TableRule.model_validate(item) for item in value]

    @field_validator("control_plane_sequence")
    @classmethod
    def _validate_control_plane_sequence(cls, value: List[Any]) -> List[ControlPlaneOperation]:
        normalized_items = [_normalize_operation_dict(item) for item in value]
        return [
            item if isinstance(item, ControlPlaneOperation) else ControlPlaneOperation.model_validate(item)
            for item in normalized_items
        ]

    @field_validator("execution_sequence")
    @classmethod
    def _validate_execution_sequence(cls, value: List[Any]) -> List[ExecutionOperation]:
        normalized_items = [_normalize_operation_dict(item) for item in value]
        return [item if isinstance(item, ExecutionOperation) else ExecutionOperation.model_validate(item) for item in normalized_items]


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
    packet_predictions: List[Any]
    assumptions: List[str] = Field(default_factory=list)

    @field_validator("packet_predictions")
    @classmethod
    def _validate_packet_predictions(cls, value: List[Any]) -> List[OraclePacketPrediction]:
        return [
            item if isinstance(item, OraclePacketPrediction) else OraclePacketPrediction.model_validate(item)
            for item in value
        ]


class RuntimePacketObservation(BaseModel):
    packet_id: int
    observed_outcome: Literal["deliver", "drop", "unknown"]
    observed_rx_host: Optional[str] = None
    observation_note: Optional[str] = None


class Agent1Output(BaseModel):
    """Semantic Analyzer output: either a TaskSpec, or questions for the user."""

    kind: Literal["task", "questions"]
    task: Optional[Any] = None
    questions: Optional[List[Any]] = None

    @field_validator("task")
    @classmethod
    def _validate_task(cls, value: Optional[Any]) -> Optional[TaskSpec]:
        if value is None or isinstance(value, TaskSpec):
            return value
        return TaskSpec.model_validate(value)

    @field_validator("questions")
    @classmethod
    def _validate_questions(cls, value: Optional[List[Any]]) -> Optional[List[UserQuestion]]:
        if value is None:
            return None
        return [item if isinstance(item, UserQuestion) else UserQuestion.model_validate(item) for item in value]


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

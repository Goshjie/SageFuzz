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
    internal_host: Optional[str] = Field(None, description="Host id that can initiate (client).")
    external_host: Optional[str] = Field(None, description="Host id that can only reply (server side).")
    include_negative_external_initiation: Optional[bool] = Field(
        None, description="Whether to add a negative case where external initiates."
    )


class UserQuestion(BaseModel):
    """A question that Agent1 asks the user, tied to a specific intent field."""

    field: Literal[
        "feature_under_test",
        "intent_text",
        "topology_zone_mapping",
        "internal_host",
        "external_host",
        "include_negative_external_initiation",
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
    internal_host: str = Field(..., description="Host id that can initiate (client).")
    external_host: str = Field(..., description="Host id that can only reply (server side).")
    require_positive_handshake: bool = Field(
        True, description="Require internal->external initiation with time-ordered replies."
    )
    include_negative_external_initiation: bool = Field(
        True,
        description="If true, include an external->internal SYN as a negative-direction testcase packet.",
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


class RuleSetCandidate(BaseModel):
    task_id: str
    entities: List[TableRule]


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
    meta: Dict[str, Any] = Field(default_factory=dict)

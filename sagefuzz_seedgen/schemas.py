from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class TaskSpec(BaseModel):
    """High-level packet generation task produced by Semantic Analyzer.

    Note: this is intentionally small; the agent is expected to query tools for evidence.
    """

    task_id: str = Field(..., description="Stable id for this task.")
    task_description: str = Field(..., description="Human readable intent.")
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
    meta: Dict[str, Any] = Field(default_factory=dict)

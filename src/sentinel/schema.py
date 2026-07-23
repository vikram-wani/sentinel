"""Normalized trace schema.

Every parser converts its input format into this. Every detector reads only this.
Keeping the schema small and boring is the point: analyzers should never need to
know whether a trace came from a JSON dump, LangSmith, or OTel.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class StepType(str, Enum):
    USER = "user"                # user message
    PLAN = "plan"                # planner / routing decision
    TOOL_CALL = "tool_call"      # agent invokes a tool
    TOOL_RESULT = "tool_result"  # tool returns
    RETRIEVAL = "retrieval"      # retriever invocation + returned docs
    LLM_CALL = "llm_call"        # raw model call (non-final)
    ASSISTANT = "assistant"      # final (or intermediate) assistant message


class Step(BaseModel):
    index: int
    type: StepType
    name: Optional[str] = None            # tool name, model name, retriever name
    input: Optional[Any] = None           # args / prompt / query
    output: Optional[Any] = None          # result / completion / docs
    error: Optional[str] = None           # tool/API error, if any
    tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    meta: dict[str, Any] = Field(default_factory=dict)


class Expectations(BaseModel):
    """Optional per-trace spec. When present, enables spec-based detectors."""
    expected_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    must_be_grounded: bool = True         # final answer claims must trace to evidence
    max_tool_repeats: int = 2
    context_budget_tokens: Optional[int] = None


class Trace(BaseModel):
    trace_id: str
    app: Optional[str] = None
    steps: list[Step]
    expectations: Optional[Expectations] = None
    meta: dict[str, Any] = Field(default_factory=dict)

    @property
    def final_answer(self) -> Optional[Step]:
        for s in reversed(self.steps):
            if s.type == StepType.ASSISTANT:
                return s
        return None

    def steps_of(self, *types: StepType) -> list[Step]:
        return [s for s in self.steps if s.type in types]


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Finding(BaseModel):
    """One detector observation, anchored to a step."""
    detector: str
    category: str                 # e.g. missing_tool, ungrounded_answer, tool_loop
    step_index: int               # where the deviation occurred
    severity: Severity
    confidence: float             # 0..1; deterministic detectors emit 1.0
    evidence: list[str]           # human-readable, log-quotable facts
    fix_hint: str


class Localization(BaseModel):
    """The headline output: the first bad decision and its blast radius."""
    root_step_index: int
    root_category: str
    root_finding: Finding
    propagation: list[Finding]    # downstream findings caused/explained by root
    fix_location: str
    do_not_modify: list[str]


class IncidentReport(BaseModel):
    trace_id: str
    verdict: str                  # FAILED | HEALTHY
    localization: Optional[Localization]
    all_findings: list[Finding]

"""Deterministic detectors.

Design rule (borrowed from what actually holds up in production eval tooling):
check facts in code first; reach for an LLM only for what genuinely needs
judgment. Every detector here emits confidence=1.0 because its verdict cannot
flip between runs on identical input. That property is what makes the outputs
CI-gateable.

Each detector: (Trace) -> list[Finding].
"""
from __future__ import annotations

import json
import re
from collections import Counter

from ..schema import Finding, Severity, Step, StepType, Trace

# ---------------------------------------------------------------- helpers

_NUMBERISH = re.compile(r"(?:\b[A-Z]{2,}-\d{3,}\b|#\d{3,}|\$\d[\d,]*(?:\.\d+)?|\b\d{4,}\b|\b\d+(?:\.\d+)?%)")


def _text(x) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    return json.dumps(x, default=str)


def _evidence_corpus(trace: Trace) -> str:
    """Everything the agent legitimately observed: tool results + retrieved docs + user input."""
    parts = []
    for s in trace.steps:
        if s.type in (StepType.TOOL_RESULT, StepType.RETRIEVAL, StepType.USER):
            parts.append(_text(s.output))
            parts.append(_text(s.input))
    return " ".join(parts)


# ---------------------------------------------------------------- detectors

def detect_missing_tool(trace: Trace) -> list[Finding]:
    exp = trace.expectations
    if not exp or not exp.expected_tools:
        return []
    called = {s.name for s in trace.steps_of(StepType.TOOL_CALL)}
    findings = []
    for tool in exp.expected_tools:
        if tool not in called:
            # anchor to the decision point: the plan step if present, else first llm/assistant step
            anchor = next(
                (s for s in trace.steps if s.type == StepType.PLAN),
                next((s for s in trace.steps if s.type in (StepType.LLM_CALL, StepType.ASSISTANT)), trace.steps[0]),
            )
            findings.append(Finding(
                detector="missing_tool",
                category="missing_tool",
                step_index=anchor.index,
                severity=Severity.HIGH,
                confidence=1.0,
                evidence=[
                    f"Spec expects tool '{tool}' to be called for this query.",
                    f"Tools actually called: {sorted(t for t in called if t)or ['<none>']}.",
                    f"Decision point: step {anchor.index} ({anchor.type.value}).",
                ],
                fix_hint=f"Planner/routing prompt does not enforce mandatory '{tool}' invocation. Add a routing constraint; do not switch models.",
            ))
    return findings


def detect_forbidden_or_wrong_tool(trace: Trace) -> list[Finding]:
    exp = trace.expectations
    if not exp or not exp.forbidden_tools:
        return []
    findings = []
    for s in trace.steps_of(StepType.TOOL_CALL):
        if s.name in exp.forbidden_tools:
            findings.append(Finding(
                detector="wrong_tool",
                category="wrong_tool",
                step_index=s.index,
                severity=Severity.HIGH,
                confidence=1.0,
                evidence=[
                    f"Step {s.index}: agent called forbidden tool '{s.name}' with args {_text(s.input)[:120]}.",
                    f"Expected tools for this query: {exp.expected_tools or '<any allowed>'}.",
                ],
                fix_hint="Tool selection error at the planner. Tighten tool descriptions or add routing examples for this query class.",
            ))
    return findings


def detect_tool_loop(trace: Trace) -> list[Finding]:
    max_rep = trace.expectations.max_tool_repeats if trace.expectations else 2
    sig_counts: Counter = Counter()
    first_offender: dict[str, Step] = {}
    for s in trace.steps_of(StepType.TOOL_CALL):
        sig = f"{s.name}({_text(s.input)})"
        sig_counts[sig] += 1
        if sig_counts[sig] == max_rep + 1 and sig not in first_offender:
            first_offender[sig] = s
    findings = []
    for sig, s in first_offender.items():
        findings.append(Finding(
            detector="tool_loop",
            category="tool_loop",
            step_index=s.index,
            severity=Severity.MEDIUM,
            confidence=1.0,
            evidence=[
                f"Identical call repeated {sig_counts[sig]}x (budget: {max_rep}): {sig[:140]}",
                f"First over-budget repeat at step {s.index}.",
            ],
            fix_hint="Agent is not incorporating tool results into state. Check result parsing / stop conditions before touching the prompt.",
        ))
    return findings


def detect_empty_retrieval_ungrounded(trace: Trace) -> list[Finding]:
    """Retriever returned zero docs, yet the agent produced a substantive answer.

    This is the classic silent failure: the judge reading the same empty context
    would pass it. Deterministically checkable, so check it in code.
    """
    findings = []
    final = trace.final_answer
    for s in trace.steps_of(StepType.RETRIEVAL):
        docs = s.output or []
        n = len(docs) if isinstance(docs, list) else (0 if not docs else 1)
        if n == 0 and final is not None and len(_text(final.output)) > 80:
            findings.append(Finding(
                detector="empty_retrieval",
                category="ungrounded_answer",
                step_index=s.index,
                severity=Severity.CRITICAL,
                confidence=1.0,
                evidence=[
                    f"Step {s.index}: retriever '{s.name}' returned 0 documents for query {_text(s.input)[:100]!r}.",
                    f"Step {final.index}: agent produced a {len(_text(final.output))}-char substantive answer anyway.",
                ],
                fix_hint="Two candidate fixes: (a) retrieval config (k, index coverage) if docs should exist; (b) an explicit 'refuse on empty retrieval' guard in the answer prompt. Fix (b) is the safety net either way.",
            ))
    return findings


def detect_ignored_tool_error(trace: Trace) -> list[Finding]:
    findings = []
    final = trace.final_answer
    for s in trace.steps:
        if s.type == StepType.TOOL_RESULT and s.error:
            if final is not None and "error" not in _text(final.output).lower():
                findings.append(Finding(
                    detector="ignored_error",
                    category="ignored_tool_error",
                    step_index=s.index,
                    severity=Severity.HIGH,
                    confidence=1.0,
                    evidence=[
                        f"Step {s.index}: tool '{s.name}' returned error: {s.error[:140]}",
                        f"Step {final.index}: final answer proceeds confidently without surfacing the failure.",
                    ],
                    fix_hint="Error handling gap: agent should retry or disclose. Add an error-path instruction; the model itself is not the problem.",
                ))
    return findings


def detect_fabricated_specifics(trace: Trace) -> list[Finding]:
    """Concrete identifiers/amounts in the final answer that appear in no observed evidence.

    Deliberately conservative: only flags 'hard' tokens (order IDs, dollar amounts,
    percentages, long numbers). Prose claims are left to the optional LLM layer.
    """
    exp = trace.expectations
    if exp and not exp.must_be_grounded:
        return []
    final = trace.final_answer
    if final is None:
        return []
    answer = _text(final.output)
    corpus = _evidence_corpus(trace)
    fabricated = sorted({tok for tok in _NUMBERISH.findall(answer) if tok not in corpus})
    if not fabricated:
        return []
    return [Finding(
        detector="fabricated_specifics",
        category="fabricated_specifics",
        step_index=final.index,
        severity=Severity.CRITICAL,
        confidence=1.0,
        evidence=[
            f"Final answer contains concrete values not present in any tool result, retrieved doc, or user input: {fabricated}.",
            "Every hard value in a grounded answer must be traceable to observed evidence.",
        ],
        fix_hint="Grounding failure at answer generation. Add structured-output validation / cite-your-source constraint.",
    )]


def detect_context_overflow(trace: Trace) -> list[Finding]:
    budget = trace.expectations.context_budget_tokens if trace.expectations else None
    if not budget:
        return []
    running = 0
    for s in trace.steps:
        running += s.tokens or 0
        if running > budget:
            return [Finding(
                detector="context_overflow",
                category="context_overflow",
                step_index=s.index,
                severity=Severity.MEDIUM,
                confidence=1.0,
                evidence=[
                    f"Cumulative tokens exceeded budget ({running} > {budget}) at step {s.index}.",
                    "Later context (including early instructions) may have been truncated.",
                ],
                fix_hint="Introduce summarization/compaction before this point, or raise the budget deliberately.",
            )]
    return []


ALL_DETECTORS = [
    detect_missing_tool,
    detect_forbidden_or_wrong_tool,
    detect_tool_loop,
    detect_empty_retrieval_ungrounded,
    detect_ignored_tool_error,
    detect_fabricated_specifics,
    detect_context_overflow,
]


def run_all(trace: Trace) -> list[Finding]:
    findings: list[Finding] = []
    for det in ALL_DETECTORS:
        findings.extend(det(trace))
    return sorted(findings, key=lambda f: f.step_index)

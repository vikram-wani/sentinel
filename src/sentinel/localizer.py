"""Failure Localization.

Most eval tooling answers "did the agent fail?" Sentinel answers "where did the
run first go wrong, and what downstream damage is explained by that node?"

v0 rule, deliberately simple and defensible:
  1. Run all deterministic detectors.
  2. The root is the earliest finding by step index, with severity as tiebreaker
     and one causal override: if a decision-level failure (missing_tool,
     wrong_tool) exists, it dominates same-or-later symptom-level findings
     (fabricated_specifics, ungrounded_answer) because fabrication is the
     *consequence* of not fetching the facts.
  3. Everything after the root is propagation, not additional root causes.

This is exactly the property a debugging tool needs: one incident -> one fix
location -> an explicit "do not modify" list, so teams stop shotgun-patching
prompts, retrieval, and models simultaneously.
"""
from __future__ import annotations

from .schema import Finding, IncidentReport, Localization, Trace
from .detectors.deterministic import run_all
from .reasoning_tier import detect_reasoning_errors

_DECISION_CATEGORIES = {"missing_tool", "wrong_tool", "tool_loop"}
_SYMPTOM_CATEGORIES = {"fabricated_specifics", "ungrounded_answer", "ignored_tool_error"}

_SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_FIX_LOCATION = {
    "missing_tool": "Planner prompt / routing policy",
    "wrong_tool": "Planner prompt / tool descriptions",
    "tool_loop": "Agent state handling / stop conditions",
    "ungrounded_answer": "Retrieval config AND answer-prompt empty-context guard",
    "ignored_tool_error": "Tool-error handling path in agent prompt",
    "fabricated_specifics": "Answer generation: grounding/citation constraint",
    "context_overflow": "Context management (compaction/summarization)",
    "reasoning_error": "Answer-generation prompt: consistency/grounding check against retrieved evidence",
}

_DO_NOT_MODIFY = {
    "missing_tool": ["Retrieval pipeline", "Answer generation prompt", "Model choice"],
    "wrong_tool": ["Retrieval pipeline", "Model choice"],
    "tool_loop": ["Planner prompt (first verify state handling)", "Model choice"],
    "ungrounded_answer": ["Planner routing", "Model choice"],
    "ignored_tool_error": ["Retrieval pipeline", "Model choice"],
    "fabricated_specifics": ["Retrieval pipeline (evidence was available)", "Model choice"],
    "context_overflow": ["Prompts (content is fine; volume is not)"],
    "reasoning_error": ["Retrieval pipeline (evidence was correct)", "Tool selection"],
}


def localize(findings: list[Finding]) -> Localization | None:
    if not findings:
        return None
    decision = [f for f in findings if f.category in _DECISION_CATEGORIES]
    # If a wrong-tool substitution occurred, it *explains* the missing expected tool.
    # Report the substitution as root; the omission is its shadow, not a second cause.
    if any(f.category == "wrong_tool" for f in decision):
        decision = [f for f in decision if f.category != "missing_tool"]

    # Deterministic findings (confidence 1.0 — tiers 1 and 2's confirmed heuristic
    # hits) always outrank probabilistic ones (Tier 3 judge, unconfirmed Tier 2
    # candidates), regardless of which step index sorts earlier. A guess about
    # meaning does not get to override a checkable fact.
    deterministic = [f for f in findings if f.confidence >= 1.0]

    if decision:
        pool = decision
    elif deterministic:
        pool = deterministic
    else:
        pool = findings  # only probabilistic findings exist — use them, clearly labeled as such

    root = sorted(pool, key=lambda f: (f.step_index, _SEV_RANK.get(f.severity.value, 9)))[0]
    propagation = [f for f in findings if f is not root]
    return Localization(
        root_step_index=root.step_index,
        root_category=root.category,
        root_finding=root,
        propagation=propagation,
        fix_location=_FIX_LOCATION.get(root.category, "Investigate manually"),
        do_not_modify=_DO_NOT_MODIFY.get(root.category, []),
    )


def analyze(trace: Trace) -> IncidentReport:
    findings = run_all(trace) + detect_reasoning_errors(trace)
    loc = localize(findings)
    return IncidentReport(
        trace_id=trace.trace_id,
        verdict="FAILED" if findings else "HEALTHY",
        localization=loc,
        all_findings=findings,
    )

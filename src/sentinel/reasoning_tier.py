"""Ties Tier 2 (candidate generation) to Tier 3 (confirmation) and produces
the Finding objects the localizer actually consumes. This is the only place
in the codebase where "did we check with the judge" turns into a concrete
confidence number.
"""
from __future__ import annotations

from .detectors.heuristic import find_candidates
from .judge import judge_available, judge_candidate
from .schema import Finding, Severity, Trace

UNCONFIRMED_CONFIDENCE = 0.55  # deliberately well below 1.0 — this is a guess, not a fact


def detect_reasoning_errors(trace: Trace) -> list[Finding]:
    candidates = find_candidates(trace)
    findings: list[Finding] = []

    have_judge = judge_available()

    for c in candidates:
        if have_judge:
            verdict = judge_candidate(c)
            if verdict is None:
                # Key present but call failed (network, rate limit, bad key) —
                # fall back to the unconfirmed candidate rather than silently
                # dropping it. A failed API call is not evidence of anything.
                findings.append(_unconfirmed_finding(c, note="judge call failed, falling back to heuristic-only"))
                continue
            if not verdict.contradicts:
                continue  # correctly suppressed — this is tier 3 doing its job
            findings.append(Finding(
                detector="llm_judge_tier3",
                category="reasoning_error",
                step_index=c.answer_step_index,
                severity=Severity.CRITICAL,
                confidence=verdict.confidence,
                evidence=[
                    f"Evidence (step {c.step_index}): {c.evidence_sentence!r}",
                    f"Answer contradicts it: {verdict.reasoning}" if verdict.reasoning else "Answer directly contradicts this evidence.",
                ],
                fix_hint="Answer-generation step is not respecting retrieved constraints. Add an explicit grounding/consistency check before the final response, or route through a stricter answer template for policy-bound questions.",
            ))
        else:
            findings.append(_unconfirmed_finding(c))

    return findings


def _unconfirmed_finding(c, note: str | None = None) -> Finding:
    evidence = [
        f"Evidence (step {c.step_index}): {c.evidence_sentence!r}",
        f"Answer (step {c.answer_step_index}) shares topic words {sorted(c.topic_overlap)} and reads as affirmative.",
        "UNCONFIRMED: set ANTHROPIC_API_KEY to enable Tier 3 judge confirmation of this candidate.",
    ]
    if note:
        evidence.append(note)
    return Finding(
        detector="contradiction_heuristic",
        category="reasoning_error",
        step_index=c.answer_step_index,
        severity=Severity.HIGH,  # one notch below the judge-confirmed CRITICAL, reflecting lower certainty
        confidence=UNCONFIRMED_CONFIDENCE,
        evidence=evidence,
        fix_hint="Possible contradiction between retrieved evidence and the final answer — unconfirmed by the LLM judge. Review manually, or enable Tier 3 for automatic confirmation.",
    )

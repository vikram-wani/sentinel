"""Ties Tier 2 (candidate generation) to Tier 3 (confirmation) and produces
the Finding objects the localizer actually consumes. This is the only place
in the codebase where "did we check with the judge" turns into a concrete
confidence number.
"""
from __future__ import annotations

from .detectors.heuristic import find_candidates
from .detectors.completeness_heuristic import find_candidates as completeness_find_candidates
from .detectors.completeness_heuristic import find_descriptive_candidates as completeness_find_descriptive_candidates
from .judge import judge_completeness
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

def detect_completeness_errors(trace: Trace) -> list[Finding]:
    """Runs both completeness signals. Signal A (a missing identifier) and
    Signal B (a descriptive continuation cue with nothing to hook onto) can
    both fire on the same trace independently -- that's expected, not a
    bug, they're catching different-shaped evidence for what could be the
    same underlying omission or two different ones. Each gets judged on its
    own terms."""
    findings: list[Finding] = []
    have_judge = judge_available()

    for c in completeness_find_candidates(trace):  # Signal A
        if have_judge:
            verdict = judge_completeness(c.user_text, [c.call_args])
            if verdict is None:
                findings.append(_unconfirmed_signal_a_finding(
                    c, note="judge call failed, falling back to heuristic-only"))
                continue
            if not verdict.incomplete:
                continue  # correctly suppressed -- the number was irrelevant, not omitted
            findings.append(Finding(
                detector="llm_judge_tier3_completeness_a",
                category="incomplete_arguments",
                step_index=c.call_step_index,
                severity=Severity.CRITICAL,
                confidence=verdict.confidence,
                evidence=[
                    f"User (step {c.user_step_index}) mentioned {c.mentioned_value!r}, "
                    f"which does not appear in the final action's arguments.",
                    f"Judge: {verdict.reasoning}" if verdict.reasoning
                    else "Judge confirmed this was omitted from the executed action.",
                    f"Missing: {verdict.missing_item}" if verdict.missing_item else "",
                ],
                fix_hint="Before executing a one-time consequential action, cross-check every "
                         "item the user mentioned against the call's arguments, not just the "
                         "most recently discussed one.",
            ))
        else:
            findings.append(_unconfirmed_signal_a_finding(c))

    for c in completeness_find_descriptive_candidates(trace):  # Signal B
        if have_judge:
            verdict = judge_completeness(c.full_transcript, c.all_call_args)
            if verdict is None:
                findings.append(_unconfirmed_signal_b_finding(
                    c, note="judge call failed, falling back to heuristic-only"))
                continue
            if not verdict.incomplete:
                continue  # correctly suppressed -- the full request WAS addressed
            findings.append(Finding(
                detector="llm_judge_tier3_completeness_b",
                category="incomplete_arguments",
                step_index=c.call_step_index,
                severity=Severity.CRITICAL,
                confidence=verdict.confidence,
                evidence=[
                    f"User (step {c.trigger_step_index}) used a continuation cue "
                    f"({c.trigger_phrase!r}), suggesting more than one request in this "
                    f"conversation.",
                    f"Judge: {verdict.reasoning}" if verdict.reasoning
                    else "Judge confirmed the full conversation was not fully addressed.",
                    f"Missing: {verdict.missing_item}" if verdict.missing_item else "",
                ],
                fix_hint="Before executing a one-time consequential action, re-read the full "
                         "conversation for every distinct request, not just the most recent one.",
            ))
        else:
            findings.append(_unconfirmed_signal_b_finding(c))

    return findings


def _unconfirmed_signal_a_finding(c, note: str | None = None) -> Finding:
    evidence = [
        f"User (step {c.user_step_index}) mentioned {c.mentioned_value!r}, "
        f"which does not appear anywhere in this trace's consequential tool calls.",
        "UNCONFIRMED: set ANTHROPIC_API_KEY to enable Tier 3 judge confirmation of this candidate.",
    ]
    if note:
        evidence.append(note)
    return Finding(
        detector="completeness_heuristic_a",
        category="incomplete_arguments",
        step_index=c.call_step_index,
        severity=Severity.HIGH,
        confidence=UNCONFIRMED_CONFIDENCE,
        evidence=evidence,
        fix_hint="Possible omitted item from a consequential action -- unconfirmed by the LLM "
                 "judge. Review manually, or enable Tier 3 for automatic confirmation.",
    )


def _unconfirmed_signal_b_finding(c, note: str | None = None) -> Finding:
    evidence = [
        f"User (step {c.trigger_step_index}) used a continuation cue ({c.trigger_phrase!r}) "
        f"with no matching identifier check possible -- unconfirmed without a live judge.",
        "UNCONFIRMED: set ANTHROPIC_API_KEY to enable Tier 3 judge confirmation of this candidate.",
    ]
    if note:
        evidence.append(note)
    return Finding(
        detector="completeness_heuristic_b",
        category="incomplete_arguments",
        step_index=c.call_step_index,
        severity=Severity.HIGH,
        confidence=UNCONFIRMED_CONFIDENCE,
        evidence=evidence,
        fix_hint="Possible incomplete action -- a continuation cue was found with no live judge "
                 "available to confirm. Review manually, or enable Tier 3.",
    )

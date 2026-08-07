"""Tier 2 — completeness heuristic.

Design role: same as heuristic.py's contradiction checker, a candidate
generator, not a verdict. Where that module asks "does the answer contradict
retrieved evidence," this one asks a different question: "did the user
mention something that never made it into the final consequential action?"

Mechanical, not semantic, on purpose. It does not try to count how many
distinct requests the user made (fuzzy, NLU-shaped, and the kind of judgment
call this project has declined to fake with a regex before -- see STUDY.md,
"What I chose not to build, and why"). It checks one hard fact instead: does
an item-identifier-shaped number the user typed appear anywhere in the
arguments of the final consequential tool call? If the user typed a number
that never shows up in what actually got executed, that is a candidate worth
asking the judge about, not a confirmed omission -- the number could be
irrelevant (a phone number, a zip code fragment) or actually the omitted
item. Precision is Tier 3's job, same as it's always been.

  - Judge available:   candidate is sent for confirmation. INCOMPLETE becomes
    a Finding at the judge's own confidence. COMPLETE is correctly
    suppressed -- the number was irrelevant, not omitted.
  - Judge unavailable:  the candidate surfaces directly as a Finding, at
    confidence well below 1.0, explicitly labeled unconfirmed.

This module never calls a model. It only ever produces candidates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..schema import StepType, Trace

_CONSEQUENTIAL_ITEM_TOOLS = {
    "return_delivered_order_items",
    "exchange_delivered_order_items",
    "modify_pending_order_items",
}

# Item/product identifiers in this domain run 6+ digits. Shorter numbers
# (zip codes are 5, phone extensions shorter still) are excluded on purpose
# to keep this a narrow signal, not a trigger on every number in a message.
_ITEM_ID_PATTERN = re.compile(r"\b\d{6,}\b")

# Signal B's trigger: a continuation cue in a message that isn't the user's
# first, the shape of "I already asked for X, here's one more thing." Kept
# small and literal on purpose, same recall-over-precision posture as every
# Tier 2 heuristic in this project -- a candidate, not a verdict.
_CONTINUATION_CUES = [
    "also", "and also", "as well", "additionally", "one more thing",
    "another thing", "in addition", "can you also", "could you also",
]


def _final_consequential_call(trace: Trace):
    """The single source of truth for 'what did the agent actually execute,'
    used by both completeness signals so they never drift out of sync about
    which call is being checked."""
    return next(
        (s for s in reversed(trace.steps)
         if s.type == StepType.TOOL_CALL and s.name in _CONSEQUENTIAL_ITEM_TOOLS),
        None,
    )


def _text(x) -> str:
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, (list, tuple)):
        return " ".join(_text(item) for item in x)
    return str(x)


def _all_call_argument_values(trace: Trace) -> set[str]:
    """Every string/number value that appears in any tool call's arguments
    anywhere in the trace -- not just the final call. A value the user typed
    that shows up in an *earlier*, different call (e.g. a get_product_details
    lookup) is still accounted for; it just never made it into the
    consequential action, which is a different, better-scoped candidate
    than 'this number appears nowhere at all.'"""
    values: set[str] = set()
    for step in trace.steps:
        if step.type != StepType.TOOL_CALL or not isinstance(step.input, dict):
            continue
        for v in step.input.values():
            if isinstance(v, (str, int, float)):
                values.add(str(v))
            elif isinstance(v, list):
                values.update(str(x) for x in v)
    return values


@dataclass
class CompletenessCandidate:
    user_step_index: int       # where the user mentioned the unaccounted-for value
    mentioned_value: str       # the item-id-shaped number in question
    user_text: str             # full user message it came from, for judge context
    call_step_index: int       # the final consequential call
    call_args: dict


def find_candidates(trace: Trace) -> list[CompletenessCandidate]:
    """Signal A. Pure, deterministic scan. No model calls. Returns [] on no
    signal. Fires per distinct missing identifier -- each one is a separate,
    independently checkable fact, so multiple candidates from one trace is
    correct, not redundant."""
    final_call = _final_consequential_call(trace)
    if final_call is None:
        return []

    all_call_values = _all_call_argument_values(trace)

    candidates: list[CompletenessCandidate] = []
    seen_values: set[str] = set()  # avoid duplicate candidates for the same number
    for step in trace.steps:
        if step.type != StepType.USER:
            continue
        user_text = _text(step.input)
        for match in _ITEM_ID_PATTERN.finditer(user_text):
            value = match.group()
            if value in seen_values or value in all_call_values:
                continue
            seen_values.add(value)
            candidates.append(CompletenessCandidate(
                user_step_index=step.index,
                mentioned_value=value,
                user_text=user_text,
                call_step_index=final_call.index,
                call_args=final_call.input or {},
            ))
    return candidates


@dataclass
class DescriptiveCompletenessCandidate:
    trigger_step_index: int    # where the continuation cue was found
    trigger_phrase: str        # the cue itself ("also", "as well", ...)
    full_request_text: str     # every user message combined, not just one --
                                # the omitted item may have been named earlier
                                # while the cue appears later
    call_step_index: int
    call_args: dict


def find_descriptive_candidates(trace: Trace) -> list[DescriptiveCompletenessCandidate]:
    """Signal B. Catches the shape Signal A structurally cannot: a purely
    descriptive omission with no identifier at all to hook onto ("also, can
    you return my backpack" -- nothing to match against any call argument).

    Produces at most one candidate per trace, on purpose, not one per cue
    occurrence. Signal A's multiple-candidates-per-trace makes sense because
    each missing number is an independently checkable fact. Signal B has no
    such per-item granularity -- its candidate is inherently a single,
    holistic question ("does this action cover the whole conversation"), so
    generating one candidate per "also" would just mean asking the judge the
    identical question multiple times.

    Real-world validation status, stated plainly: built and tested against a
    synthetic example, not yet confirmed against a real trace the way Signal
    A was validated against task21. None of the 35 traces labeled during Day
    4 necessarily exercise this exact shape (every one seen so far involved
    at least one concrete number). Flagged in ROADMAP.md until a live test
    against real data closes that gap.
    """
    final_call = _final_consequential_call(trace)
    if final_call is None:
        return []

    user_steps = [s for s in trace.steps if s.type == StepType.USER]
    if len(user_steps) < 2:
        return []  # a continuation cue needs something to continue from

    full_request_text = " ".join(_text(s.input) for s in user_steps)

    # Skip the first user message -- an opening request can't be a
    # "continuation" of anything yet.
    for step in user_steps[1:]:
        text_lower = _text(step.input).lower()
        for cue in _CONTINUATION_CUES:
            if cue in text_lower:
                return [DescriptiveCompletenessCandidate(
                    trigger_step_index=step.index,
                    trigger_phrase=cue,
                    full_request_text=full_request_text,
                    call_step_index=final_call.index,
                    call_args=final_call.input or {},
                )]
    return []

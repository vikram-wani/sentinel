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
from itertools import combinations, product

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
    """A tool listed twice in expected_tools means "must be called at least
    twice" (e.g. cancelling two separate orders with the same tool, different
    arguments). This was originally a set-membership check, which meant a
    tool called ONCE registered as "present" even when the trace required a
    second call with different arguments -- a real bug, found via a real
    tau-bench trace (task 81: agent cancels one of two required orders,
    calls cancel_pending_order once, old logic saw it in the called-set and
    stayed silent). Counter-based comparison catches this; plain presence
    checks (single expected occurrence) behave identically to before.
    """
    exp = trace.expectations
    if not exp or not exp.expected_tools:
        return []
    called_counts = Counter(s.name for s in trace.steps_of(StepType.TOOL_CALL))
    expected_counts = Counter(exp.expected_tools)
    findings = []
    for tool, required_n in expected_counts.items():
        actual_n = called_counts.get(tool, 0)
        if actual_n < required_n:
            # anchor to the decision point: the plan step if present, else first llm/assistant step
            # NOTE: for the "called some but not enough" case there is no single
            # missing-call step to point to -- this anchor is a defensible
            # approximation (earliest planning-like decision), not a precise
            # locate of where the extra call should have happened.
            anchor = next(
                (s for s in trace.steps if s.type == StepType.PLAN),
                next((s for s in trace.steps if s.type in (StepType.LLM_CALL, StepType.ASSISTANT)), trace.steps[0]),
            )
            times_desc = f"called {actual_n} time(s), expected {required_n}" if actual_n else "never called"
            findings.append(Finding(
                detector="missing_tool",
                category="missing_tool",
                step_index=anchor.index,
                severity=Severity.HIGH,
                confidence=1.0,
                evidence=[
                    f"Spec expects tool '{tool}' to be called {required_n} time(s) for this query; {times_desc}.",
                    f"Tools actually called (with counts): {dict(called_counts) or '<none>'}.",
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


_DISCLOSURE_PHRASES = [
    "error", "unable to", "unfortunately", "cannot", "can't", "can not",
    "sorry", "apologize", "not able", "failed", "an issue", "wasn't able",
    "was not able", "no longer possible", "not possible",
]


def _identifier_values(args) -> set[str]:
    """Pull out string values from a tool call's arguments that look like
    entity identifiers (order IDs, item IDs, user IDs) worth matching against
    later calls, to detect 'tried a different tool on the same thing.'"""
    if not isinstance(args, dict):
        return set()
    out = set()
    for v in args.values():
        if isinstance(v, str) and len(v) >= 5:
            out.add(v)
        elif isinstance(v, list):
            out.update(x for x in v if isinstance(x, str) and len(x) >= 5)
    return out


def _same_purpose_family(name_a: str, name_b: str) -> bool:
    """Two tool names count as alternative methods for the same goal if they
    share everything up through a '_by_' marker (find_user_id_by_email vs
    find_user_id_by_name_zip): different data, same purpose, and a failure
    in one followed by success in the other is a retry, not a cover-up.
    Found necessary because the argument-overlap check alone misses this --
    an email and a name-plus-zip share no string value at all."""
    marker = "_by_"
    if marker in name_a and marker in name_b:
        return name_a.split(marker)[0] == name_b.split(marker)[0]
    return False


def detect_ignored_tool_error(trace: Trace) -> list[Finding]:
    """A tool error is only a real problem if the agent neither recovered
    from it nor told the user about it. The original version of this
    detector checked only whether the literal word "error" appeared in the
    final answer -- which flagged routine, successfully-recovered retries
    (an auth lookup failing, then correctly falling back to a different
    method) as if the agent had silently covered up a failure. Found via
    real tau-bench traces (task28, task98), not synthetic ones: 81 of 186
    false positives in a 274-trace precision check traced to this single
    gap. Fixed two ways: check for a later successful action addressing the
    same tool or the same entity (recovery), and broaden disclosure
    detection past the single word "error" (honest reporting in the agent's
    own words, not just that one token).
    """
    findings = []
    final = trace.final_answer
    final_text_lower = _text(final.output).lower() if final else ""

    tool_calls = [s for s in trace.steps if s.type == StepType.TOOL_CALL]
    tool_results = [s for s in trace.steps if s.type == StepType.TOOL_RESULT]

    for err_result in tool_results:
        if not err_result.error:
            continue

        # Find the call that produced this error: nearest preceding TOOL_CALL
        # with the same name and not already matched to an earlier result.
        failed_call = next(
            (c for c in reversed(tool_calls) if c.name == err_result.name and c.index <= err_result.index),
            None,
        )
        failed_ids = _identifier_values(failed_call.input) if failed_call else set()

        # Recovery check: does any later successful result either reuse the
        # same tool, or touch the same entity via a different tool?
        recovered = False
        for later_result in tool_results:
            if later_result.index <= err_result.index or later_result.error:
                continue
            if later_result.name == err_result.name:
                recovered = True
                break
            if _same_purpose_family(err_result.name or "", later_result.name or ""):
                recovered = True
                break
            later_call = next((c for c in tool_calls if c.name == later_result.name
                                and c.index <= later_result.index), None)
            if later_call and failed_ids & _identifier_values(later_call.input):
                recovered = True
                break

        if recovered:
            continue

        disclosed = any(p in final_text_lower for p in _DISCLOSURE_PHRASES)
        if disclosed:
            continue

        findings.append(Finding(
            detector="ignored_error",
            category="ignored_tool_error",
            step_index=err_result.index,
            severity=Severity.HIGH,
            confidence=1.0,
            evidence=[
                f"Step {err_result.index}: tool '{err_result.name}' returned error: {err_result.error[:140]}",
                f"No later successful call retried the same tool or touched the same entity.",
                f"Step {final.index if final else '?'}: final answer does not acknowledge the failure "
                f"(checked for {len(_DISCLOSURE_PHRASES)} common disclosure phrasings, found none).",
            ],
            fix_hint="Error handling gap: agent should retry or disclose. Add an error-path instruction; the model itself is not the problem.",
        ))
    return findings


_NUMBER_IN_TEXT = re.compile(r"-?\d[\d,]*\.?\d*")


def _corpus_numeric_values(corpus: str) -> set[float]:
    """All numbers appearing anywhere in evidence, parsed to float. Used to
    catch sign-flipped matches: a stored price_difference of -16.63 (negative
    because it's a refund direction) and an answer correctly telling the
    customer "$16.63 will be refunded" (positive, because that's how a human
    describes a refund) are the same real number. A literal substring check
    treats these as unrelated and flags a correct answer as fabricated."""
    out = set()
    for m in _NUMBER_IN_TEXT.finditer(corpus):
        try:
            out.add(float(m.group().replace(",", "")))
        except ValueError:
            pass
    return out


_ARITHMETIC_MAGNITUDE_CAP = 100_000  # excludes ID-shaped numbers (item IDs, order
# fragments, which run 6-10+ digits in this domain) from arithmetic candidacy.
# Those are identifiers, not quantities to combine, and including them would
# risk a coincidental sum or difference matching some real dollar amount by
# chance rather than by actual derivation.


def _derivable_from_arithmetic(val: float, corpus_numbers: set[float]) -> bool:
    """Catches a correctly-computed value that was never itself retrieved as a
    single number, only produced by arithmetic the agent did on its own
    without calling calculate(). Found via a real trace: task21's final
    answer states a gift card balance of $52.36. That number is a two-level
    derivation, 86 (the starting balance) minus a price difference that is
    itself 268.77 minus 235.13, three grounded numbers combined, not two.
    An earlier version of this check only tried pairs and missed it;
    verified directly against the real trace before shipping this version,
    not assumed to be sufficient from the pair case alone.

    Checks every combination of 2 or 3 grounded numbers, in every +/- sign
    pattern, which covers any chain of addition and subtraction regardless
    of nesting (a - (b - c) reduces to a - b + c, a signed sum, so this
    formulation needs no special-casing for "nested" derivations). Stops at
    3 terms on purpose: real cost, not free, roughly 30-120ms per trace on
    a full search of a realistically sized evidence corpus (measured, not
    estimated), which is acceptable for a single trace but adds up over a
    460-trace batch run. Going to 4+ terms would also raise the risk of a
    coincidental match, several unrelated numbers happening to sum to a
    genuinely fabricated value by chance. 3 terms is the boundary that
    solves every real case found so far without over-reaching."""
    candidates = [c for c in corpus_numbers if abs(c) < _ARITHMETIC_MAGNITUDE_CAP]
    for n_terms in (2, 3):
        for combo in combinations(candidates, n_terms):
            for signs in product([1, -1], repeat=n_terms):
                total = sum(s * c for s, c in zip(signs, combo))
                if abs(total - val) < 0.01:
                    return True
    return False


def _is_grounded(tok: str, corpus: str, corpus_numbers: set[float]) -> bool:
    if tok in corpus:
        return True
    # Try numeric comparison (handles $, %, comma formatting, and sign flips)
    stripped = tok.lstrip("$#").rstrip("%").replace(",", "")
    try:
        val = float(stripped)
    except ValueError:
        return False
    if any(abs(val - c) < 0.01 or abs(-val - c) < 0.01 for c in corpus_numbers):
        return True
    return _derivable_from_arithmetic(val, corpus_numbers)


def detect_fabricated_specifics(trace: Trace) -> list[Finding]:
    """Concrete identifiers/amounts in the final answer that appear in no observed evidence.

    Deliberately conservative: only flags 'hard' tokens (order IDs, dollar amounts,
    percentages, long numbers). Prose claims are left to the optional LLM layer.

    Numeric tokens are compared by value, not literal string, and checked
    against both the value and its negation (see _is_grounded): a refund
    amount is naturally reported as positive even when its source
    price-difference field is stored as negative. Non-numeric identifiers
    (order IDs, SKU-style codes) still require an exact literal match --
    there's no meaningful "value" to compare for those, only presence.
    """
    exp = trace.expectations
    if exp and not exp.must_be_grounded:
        return []
    final = trace.final_answer
    if final is None:
        return []
    answer = _text(final.output)
    corpus = _evidence_corpus(trace)
    corpus_numbers = _corpus_numeric_values(corpus)
    fabricated = sorted({tok for tok in _NUMBERISH.findall(answer)
                          if not _is_grounded(tok, corpus, corpus_numbers)})
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


_CONSEQUENTIAL_ITEM_TOOLS = {
    "return_delivered_order_items",
    "exchange_delivered_order_items",
    "modify_pending_order_items",
}


def _order_item_membership(trace: Trace) -> dict[str, set[str]]:
    """order_id -> the set of item_ids actually in that order, built from
    every get_order_details result observed in the trace. Only orders the
    agent actually retrieved are known here -- by design. If the agent never
    looked at the order that had the right item, that information was never
    in the trace to check against, and this detector correctly has nothing
    to say about it. That's a real limit, not a bug: see STUDY.md."""
    membership: dict[str, set[str]] = {}
    for s in trace.steps:
        if s.type == StepType.TOOL_RESULT and s.name == "get_order_details" and isinstance(s.output, dict):
            oid = s.output.get("order_id")
            items = s.output.get("items") or []
            if oid and isinstance(items, list):
                membership[oid] = {i.get("item_id") for i in items if isinstance(i, dict) and i.get("item_id")}
    return membership


def detect_cross_order_item_mismatch(trace: Trace) -> list[Finding]:
    """A narrow, deliberately conservative slice of the broader
    "wrong entity" failure family found during Day 4 labeling (tasks 28, 80,
    83, 21, 16, 32, 34, 72, and a task3 sibling trial all shared some form
    of "grounded value applied to the wrong target," but only one specific
    shape of that is a hard, checkable fact rather than a judgment call:
    does an item referenced in a consequential call (return, exchange,
    modify) actually belong to the order that call names? item_ids that
    belong to a *different*, also-observed order is unambiguous, no
    semantic understanding required. This does not catch cases where the
    agent picked a wrong-but-valid item within its own correct order (that
    needs to know what the user actually wanted), or cases where the
    correct item lived in an order the agent never retrieved at all (the
    information to catch it was never in the trace to begin with). Checked
    directly against Day 4's labeled traces: this pattern alone recovers
    task16-trial0; it does not recover 83, 28, 34, 72, 32, or 80, which
    require judgment this detector deliberately does not attempt.
    """
    membership = _order_item_membership(trace)
    if not membership:
        return []
    findings = []
    for s in trace.steps:
        if s.type != StepType.TOOL_CALL or s.name not in _CONSEQUENTIAL_ITEM_TOOLS:
            continue
        args = s.input or {}
        oid = args.get("order_id")
        item_ids = args.get("item_ids") or []
        if oid not in membership:
            continue  # this order was never retrieved; nothing to check against
        wrong_items = [iid for iid in item_ids if iid not in membership[oid]]
        if not wrong_items:
            continue
        # which order (if any observed) does the misplaced item actually belong to
        actual_home = next((o for o, items in membership.items() if any(w in items for w in wrong_items)), None)
        findings.append(Finding(
            detector="cross_order_item_mismatch",
            category="wrong_tool_argument",
            step_index=s.index,
            severity=Severity.CRITICAL,
            confidence=1.0,
            evidence=[
                f"Step {s.index}: {s.name} called on order {oid} with item_ids {wrong_items}, "
                f"which do not belong to that order per its own retrieved contents.",
                f"Those item(s) belong to order {actual_home} instead." if actual_home
                else "Those item(s) were not observed in any retrieved order in this trace.",
            ],
            fix_hint="Cross-reference item_ids against the target order's own contents before executing "
                      "a consequential action, not just against 'some order seen earlier in the conversation.'",
        ))
    return findings


_ORDER_LOCKING_TOOLS = {"modify_pending_order_items"}
_ORDER_TARGETING_TOOLS = {
    "modify_pending_order_address", "modify_pending_order_items",
    "modify_pending_order_payment", "cancel_pending_order",
}


def detect_ordering_error(trace: Trace) -> list[Finding]:
    """Two individually-correct operations on the same order, executed in a
    sequence where the first locks the order and the second then fails as a
    direct, structural consequence. Deliberately narrow: this only fires
    when there is an actual failed result to point to. It does not catch
    the sibling shape found in the same Day 4 sample (task41, task42) where
    the second, dependent action was never attempted at all rather than
    attempted and rejected -- that is an omission, not a sequencing error,
    and belongs to missing_tool's territory, not this detector's. Rooted at
    the earlier, locking call: that is the actual decision that mattered,
    consistent with how this exact pattern was labeled by hand during Day 4
    (task98, both trials -- two independent trials of the identical task
    that failed in the identical way, itself evidence this is a systematic
    tendency, not a one-off)."""
    findings = []
    calls = [s for s in trace.steps if s.type == StepType.TOOL_CALL]
    results = sorted((s for s in trace.steps if s.type == StepType.TOOL_RESULT), key=lambda s: s.index)

    def result_after(step_index):
        return next((r for r in results if r.index > step_index), None)

    for lock_call in calls:
        if lock_call.name not in _ORDER_LOCKING_TOOLS:
            continue
        oid = (lock_call.input or {}).get("order_id")
        if not oid:
            continue
        lock_result = result_after(lock_call.index)
        if lock_result is None or lock_result.error:
            continue  # the locking call itself didn't succeed; nothing to warn about

        for later_call in calls:
            if later_call.index <= lock_call.index or later_call.name not in _ORDER_TARGETING_TOOLS:
                continue
            if (later_call.input or {}).get("order_id") != oid:
                continue
            later_result = result_after(later_call.index)
            if later_result and later_result.error:
                findings.append(Finding(
                    detector="ordering_error",
                    category="ordering_error",
                    step_index=lock_call.index,
                    severity=Severity.HIGH,
                    confidence=1.0,
                    evidence=[
                        f"Step {lock_call.index}: {lock_call.name} succeeded on order {oid}.",
                        f"Step {later_call.index}: {later_call.name} on the same order {oid} then failed: "
                        f"{later_result.error[:120]}",
                        "The first call likely changed the order's state in a way that made the second impossible; "
                        "reversing the order would probably have let both succeed.",
                    ],
                    fix_hint="Sequence state-changing operations on the same order by dependency, not by the "
                             "order the user happened to mention them. Address/payment changes before item changes.",
                ))
                break  # one finding per locking call is enough
    return findings


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
    detect_cross_order_item_mismatch,
    detect_ordering_error,
    detect_context_overflow,
]


def run_all(trace: Trace) -> list[Finding]:
    findings: list[Finding] = []
    for det in ALL_DETECTORS:
        findings.extend(det(trace))
    return sorted(findings, key=lambda f: f.step_index)

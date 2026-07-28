# Benchmark Study: Root-Cause Localization Accuracy

This documents how Sentinel's self-benchmark is constructed, what it actually
measures, the current result, and — the part most eval write-ups skip —
where it's known to fail and why.

## Methodology

Each trace in `examples/traces/` has a hand-written ground-truth label in
`examples/labels/ground_truth.json`: the `root_category` and `root_step_index`
a human reviewer would assign after reading the full trace. `sentinel bench`
runs the deterministic localizer on every trace and checks its output against
that label. There is no partial credit — a match on category but wrong step,
or vice versa, is a failure.

Labels are written by inspecting each trace independently, before running the
localizer against it, and are not adjusted after seeing what Sentinel outputs.
Adjusting a label to match a wrong prediction would defeat the entire purpose
of a self-benchmark.

## Two rounds of traces

**Round 1 (6 traces)** covered one clean failure mode each: missing tool,
empty retrieval, tool loop, wrong tool, ignored error, and a healthy control.
Sentinel scored 6/6. That result meant almost nothing on its own — every case
had exactly one finding and no ambiguity. A localizer with no logic beyond
"return the first thing found" would also have scored 6/6.

**Round 2 (6 traces)**, added specifically to stress the parts Round 1 didn't
touch, was designed adversarially:

| Trace | What it tests |
|---|---|
| `trace-multi-fault-ordering` | Two real problems in one trace (wrong tool, then a loop on that same wrong tool). Root must be the *earlier* one, not the most recent. |
| `trace-misleading-severity` | A loud, CRITICAL-severity symptom (fabricated price) happens late; the true root is an earlier MEDIUM-severity tool loop. Tests that localization follows chronology, not how dramatic a finding looks. |
| `trace-sparse-retrieval-healthy` | Retrieval returns exactly one document (not zero) and the answer's dollar figure is grounded in it. A naive "any dollar sign is suspicious" detector would false-positive here. |
| `trace-paginated-retries-healthy` | The same tool is called twice with different arguments (pagination), not identical repeats. A naive "same tool called twice" detector would false-positive here. |
| `trace-reasoning-error-uncaught` | The agent retrieves the *correct* policy and then directly contradicts it in the final answer — a comprehension error, not a grounding or tool-routing failure. |
| `trace-context-overflow-precise` | Cumulative token budget is crossed at an exact, known step. Tests precision, not just detection. |

## Result

```
sentinel bench
```

```
Root-cause category accuracy : 11/12
Root-cause step accuracy     : 11/12
```

10 of 12 traces are unambiguous wins. The 2 precision traces
(`trace-sparse-retrieval-healthy`, `trace-paginated-retries-healthy`) confirm
the detectors don't just find problems — they correctly stay quiet when there
isn't one, which matters as much as detection does. The multi-fault and
misleading-severity cases confirm the localizer's core claim: it picks the
*earliest* causally-relevant decision, not the most recent or most severe
finding.

## The one miss, and why it's the most important row in this table

`trace-reasoning-error-uncaught` fails. The agent retrieves a policy document
that says opened items are final sale, and the final answer tells the customer
the opposite — a direct contradiction of evidence the agent itself fetched
correctly. No hard values are fabricated (there's nothing numeric to flag),
retrieval isn't empty, no tool is missing or wrong, and nothing loops or
errors. All seven deterministic detectors are silent. Sentinel reports
`HEALTHY`. It's wrong.

This is not a bug to patch by adding a regex. It's a category of failure —
semantic misreading of correctly-retrieved evidence — that pattern-matching
detectors structurally cannot catch, and it's the honest boundary of what
"deterministic, CI-gateable" localization can currently do. Closing it
requires either a constrained LLM-judge layer scoped narrowly to
claim-vs-evidence consistency, or a much more specific structural signal than
exists in this trace format today. Both are real work, not a quick fix, which
is why it's documented here instead of quietly special-cased away.

## Day 3: closing the gap without abandoning the thesis

The miss above sat unresolved for a full day on purpose — closing it properly
meant resolving a real tension first: catching a semantic contradiction seems
to require an LLM judge, and this project's core claim is "deterministic,
not another flaky LLM judge." The resolution is a two-tier addition, not one:

**Tier 2 — a code-based contradiction heuristic.** Deterministic, zero API
calls, same "cannot flip on identical input" guarantee as the original seven
detectors. It scans evidence for restrictive language ("final sale," "not
eligible," "non-refundable") near a topic the final answer treats
affirmatively, using literal keyword matching plus a topic-word overlap
check — not language understanding. It generates *candidates*, not verdicts.

**Tier 3 — a scoped LLM judge, opt-in.** Only invoked on Tier 2's candidates,
never on a whole trace. Given only the relevant evidence sentence and the
final answer, it answers one falsifiable question: does the answer contradict
the evidence? Its findings carry confidence below 1.0 and can never outrank a
deterministic finding in the localizer — the same rule that's governed this
project since Day 1.

**Without a key, Tier 2 alone resolved the original miss.** `sentinel bench`
in keyless mode now correctly localizes `trace-reasoning-error-uncaught` —
category and step both match ground truth, at confidence 0.55, explicitly
labeled `UNCONFIRMED` in the report. That's not the same as a confirmed
finding, and the tool says so in its own output rather than rounding up.

**Two new traces were added specifically to break Tier 2**, before declaring
any of this finished — the same discipline as Day 2:

- `trace-restriction-different-topic`: evidence restricts one topic (gift
  cards), the answer affirms an unrelated one (a sweater exchange). This
  caught a real bug on first run — the answer's own "non-refundable" wasn't
  recognized because the phrase list only had the spaced variant "not
  refundable," so the suppression check that should have fired silently
  didn't. Fixed by adding the hyphenated form. This is a legitimate keyword-
  coverage bug, not an architectural limit, and it's fixed.
- `trace-exception-clause-tricky`: evidence states a restriction *with an
  exception* ("final sale, except for defective products..."), and the
  answer correctly applies that exception. Tier 2 cannot parse exceptions —
  it flags this as a candidate every time, which is a **known, permanent,
  keyless-mode limitation**, left failing on purpose. Mocked end-to-end
  testing confirms Tier 3, when live, correctly reads the exception and
  returns `CONSISTENT`, resolving the trace to `HEALTHY` — but that
  resolution has only been verified against a mocked judge response in this
  environment, not a live API call. Confirming it for real requires a live
  key, run from the maintainer's own machine, before this claim moves from
  "designed and mock-tested" to "measured."

**Current result, keyless: 13/14.** The one remaining failure is the exact
one predicted and designed to fail — not a surprise, not a regression.

**Current result, Tier 3 active: 14/14, stable across 5 consecutive runs.**
A live Anthropic API key was set, `sentinel bench` was run five times
independently, and all five returned 14/14. `trace-exception-clause-tricky`
resolved correctly every time — the judge read the "except for defective
products" clause and returned `CONSISTENT`, which is precisely the case Tier
2's keyword matching structurally cannot handle.

The five-run check exists because Tier 3 is a model call, not a deterministic
check. Tiers 1–2 cannot return different answers on identical input; Tier 3
can. A single passing run would have been one sample presented as a property.
Five consecutive identical results is weak-but-real evidence of stability on
this specific set — not proof it generalizes.

| Tier | Traces resolved | Cost | Guarantee |
|---|---|---|---|
| 1 — deterministic detectors | 10 of 14 | free | confidence 1.0, cannot flip |
| 2 — code heuristic | +1 (Day 2's original miss) | free | confidence 1.0 candidate → 0.55 unconfirmed finding |
| 2, known gap | −1 (exception-clause trace) | — | requires Tier 3 to resolve |
| 3 — LLM judge (live) | +1, resolving the gap → 14/14 | opt-in, ~fractions of a cent per run | confidence < 1.0, can't outrank Tiers 1–2 |

## What Day 3 has and hasn't proven

**Measured:** Tier 2 closes Day 2's documented miss with zero API calls. Tier
3, live, closes the exception-clause gap and held 14/14 across five runs.

**Not measured, and worth stating plainly:** 14 traces where the author wrote
both the traces and the labels is not evidence of production accuracy. The
judge has been tested against one contradiction pattern (restriction vs.
affirmation) in one domain (retail returns policy). Its false-positive rate on
genuinely ambiguous real-world evidence is unknown. Five runs is enough to say
"stable on this set," not "deterministic" — and the CLI now prints that caveat
on every run rather than burying it here.

## What this benchmark is not

Fourteen traces is not statistical proof of anything. It's a floor: a fixed,
inspectable set of cases that must keep passing as the detectors evolve, run
automatically in CI on every push. Treat 13/14 keyless and 14/14 with the
judge as "hasn't regressed on these specific known cases," not as "93–100%
accurate on production traffic." The next honest step is running this against
real, messier production traces — where the failure categories won't be as
cleanly separable as they are here by construction, and where the judge will
face contradiction patterns nobody wrote a label for in advance.

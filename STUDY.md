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

## What this benchmark is not

Twelve traces is not statistical proof of anything. It's a floor: a fixed,
inspectable set of cases that must keep passing (except the one documented
miss) as the detectors evolve, run automatically in CI on every push. Treat
the 11/12 number as "hasn't regressed on these specific known cases," not as
"91% accurate on production traffic." The next honest step is running this
against real, messier production traces — where the failure categories won't
be as cleanly separable as they are here by construction.

# Sentinel

**Your agent failed. Your logs won't tell you where.**

When an LLM agent fails in production, the symptom is almost never the cause. The
hallucinated refund amount in the final answer is *downstream* of a planner that
skipped `search_orders` four steps earlier. Engineers spend 30–90 minutes per
incident replaying traces to find that first bad decision — and most incidents
never become regression tests, so they repeat.

Sentinel is an AI Reliability Engineer. Give it one failed trace; it returns:

- **The first bad decision** — the earliest node whose deviation causally explains
  everything downstream ("root cause: planner, step 1 — everything after was a consequence")
- **A fix location and an explicit "do not modify" list** — so teams stop
  shotgun-patching prompt, retrieval, and model simultaneously
- **An engineering-grade incident report** (markdown, Jira-ready)
- **A generated pytest regression test + portable eval spec** — every incident
  permanently improves the system

## Design principle: deterministic first, LLM last

Every detector in the v0 core is deterministic — missing/wrong tool, tool loops,
empty-retrieval-but-answered-anyway, ignored tool errors, fabricated hard values
(IDs, amounts, percentages absent from all observed evidence), context overflow.
Deterministic verdicts cannot flip between runs on identical input, which is what
makes them CI-gateable. An optional LLM layer narrates and handles judgment calls;
it is never the source of truth for localization.

## See it in 30 seconds — no API keys, no config

```
pip install -e .
sentinel demo
```

```
trace-refund-hallucination  FAILED
  Root cause: step 1 — missing_tool (conf 1.00)
    Spec expects tool 'search_orders' to be called for this query.
  Fix location: Planner prompt / routing policy
  Do not modify: Retrieval pipeline, Answer generation prompt, Model choice
  Propagation: fabricated_specifics ($129.99 appears in no observed evidence)
```

## Sentinel measures itself

A root-cause tool you can't measure is just another unaudited judge. Sentinel
ships with a labeled benchmark — failure traces with hand-written ground-truth
root causes — and scores its own localization against them:

```
sentinel bench
```

```
Root-cause category accuracy : 6/6
Root-cause step accuracy     : 6/6
```

The benchmark is small today and will grow adversarial cases (multi-fault traces,
misleading symptoms, root causes outside detector coverage). Accuracy on an easy
benchmark is a floor, not a claim.

## Analyze your own trace

```
sentinel analyze my_trace.json --out artifacts/
```

Produces `*.report.md`, `test_*.py` (pytest regression gate), and `*.eval.yaml`.
Trace format: see `examples/traces/`. Adapters for LangSmith / OTel / OpenAI
Responses are the next milestone — each is a single `raw -> Trace` function
against the normalized schema in `src/sentinel/schema.py`.

## Roadmap

Failure localization → automatic fix suggestions → automatic regression
generation → incident clustering → continuous production monitoring.

Apache 2.0.

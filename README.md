# Sentinel

[![CI](https://github.com/vikram-wani/sentinel/actions/workflows/ci.yml/badge.svg)](https://github.com/vikram-wani/sentinel/actions/workflows/ci.yml)

**An AI Reliability Engineer for agent failures — it finds the first bad decision, not just the fact that something broke.**

## The problem

AI agents fail differently than traditional software. There's no stack trace —
just a bad final answer buried at the end of a chain of planner decisions, tool
calls, and retrieved context. Today, diagnosing a single production incident
means an engineer manually opening traces, replaying the conversation, reading
prompts, and inspecting tool calls to reconstruct what happened. That typically
takes **30–90 minutes**, the process doesn't scale past a handful of incidents a
week, and most failures never turn into a regression test — so the same class of
bug quietly recurs.

Existing eval frameworks mostly answer *"did the agent fail?"* Sentinel answers:

> *"The first irreversible mistake happened at step 6, when the planner skipped
> `search_orders`. Everything after that — the hallucinated refund amount — was
> a consequence, not a separate bug."*

## Who this is for

- **AI platform / reliability engineers** debugging production agent incidents
- **Applied AI engineers** who own an agent's prompt, tool, and retrieval layers
- **Product managers responsible for AI quality**, who need to prioritize *is
  this a prompt problem, a retrieval problem, or a model problem?* before
  routing a fix to the right team

## Jobs it does

- *"When an AI incident happens, help me understand why it happened — fast."*
- *"When I fix an incident, automatically generate a regression test so it can't
  come back silently."*
- *"Tell me which component is actually broken, not just that the answer was
  wrong."*
- *"Help me prioritize whether this is a prompt, retrieval, tooling, or model
  issue before I touch anything."*

## How it works

Feed Sentinel one failed trace. It runs a set of deterministic detectors
(missing/wrong tool, tool loops, empty-retrieval-but-answered-anyway, ignored
tool errors, fabricated hard values not present in any observed evidence,
context overflow) and localizes the **single earliest decision** that causally
explains everything downstream. You get back:

- **Root cause**, anchored to a specific step, with quoted evidence
- **Fix location** — and an explicit **"do not modify"** list, so teams stop
  shotgun-patching prompt, retrieval, and model all at once for a bug in one place
- **An engineering-grade incident report** (Markdown, Jira-ready)
- **A generated pytest regression test + portable eval spec** — the incident
  becomes a permanent CI gate, not a one-off postmortem

Every detector is deterministic: on identical input, the verdict cannot flip
between runs. That's what makes the output safe to gate CI on, rather than
another flaky LLM-judge score. An optional LLM layer can narrate results in
plain English later, but it is never the source of truth for *where* the
failure happened.

## Success metrics this is designed against

These are the targets the tool is built to move, in line with how reliability
work gets measured on a real team — not results claimed from a 6-trace demo:

| Metric | Before | Target |
|---|---|---|
| Mean time to root cause | ~30–90 min, manual | < 5 min |
| Regression test creation | Manual, often skipped | Automatic, every incident |
| Repeat incidents (same root cause) | Recurs silently | Reduced via permanent CI gate |
| Eval/regression coverage | Ad hoc | Grows with every real incident |

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

A root-cause tool you can't measure is just another unaudited judge — the same
failure mode it's meant to catch in your agent. Sentinel ships with a labeled
benchmark (failure traces with hand-written ground-truth root causes) and
scores its own localization accuracy against it on every run:

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

## Using it on a real incident

```
sentinel analyze my_trace.json --out artifacts/
```

Drops three artifacts you can act on immediately:

- `*.report.md` — paste into Jira or Slack as the incident writeup
- `test_*.py` — a pytest regression test, ready to merge into CI
- `*.eval.yaml` — a portable eval spec for the same check outside pytest

Trace format: see `examples/traces/`. Adapters for LangSmith / OpenTelemetry /
OpenAI Responses traces are the next milestone — each is a single
`raw -> Trace` function against the normalized schema in
`src/sentinel/schema.py`, so wiring in a new trace source doesn't touch the
detectors or localizer at all.

## Roadmap

Failure localization → automatic fix suggestions → automatic regression
generation → incident clustering across repeat failures → continuous
production monitoring. Each stage builds on the same normalized trace schema,
so nothing built so far has to be thrown away.

Apache 2.0.

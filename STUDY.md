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

## Day 4: testing on data I didn't write

Every trace up to this point, all fourteen of them, I wrote myself. That's a
real, acknowledged bias: I always knew the answer before checking it. Day 4
closes that gap by running Sentinel against 460 real GPT-4o trajectories from
[tau-bench](https://github.com/sierra-research/tau-bench)'s retail domain,
traces I did not author, graded pass or fail by someone else (Sierra
Research), covering conversations I had no hand in designing.

Tau-bench gives two things: a raw conversation and a binary reward. It has no
root-cause taxonomy at all — that gap is the reason a labeling rubric had to
be built from scratch before any scoring could happen.

### The labeling process

35 traces were sampled by stratified failure type (extra tool calls, missing
tool calls, both, correct toolset with wrong outcome) plus 5 deliberately
drawn from the *passing* set, as a free false-positive check. Every trace was
read and labeled blind — category, root step, confidence, and an explicit
alternative considered — **before** Sentinel touched any of them. The rule
that has governed this project since Day 1 held without exception here too.

The rubric itself grew twice mid-labeling, each time because a real trace
forced a rule that didn't exist yet, not from armchair anticipation:

- **Rule 5**, from `task22-trial2`: a missing action has no step index the
  way a wrong action does. Root goes to where the agent moved on instead.
- **Rule 6**, from `task98-trial0`: a deviation that errors out cleanly,
  changes nothing, and gets immediately self-corrected doesn't outrank a
  later deviation that actually sticks. Rule 1's "earliest deviation" is a
  simplification; the real rule was always "earliest deviation that closes
  off correction."
- **Rule 7**, from `task76-trial3`: the corollary — when an offered
  correction is explicitly declined, root moves to the decline, not the
  original guess.

### A real bug, found and fixed the same day

`task81-trial0` needed `cancel_pending_order` called twice, for two
different orders. The agent called it once. Sentinel's `missing_tool`
detector checked *set membership* — `tool in called_tools` — so a tool
called once registered as "present," silently masking that it was required
twice. Fixed with a `Counter`-based comparison. Verified against the
original 14-trace benchmark with zero regression (still 13/14 keyless).

Independent confirmation the fix was real, not incidental: it also correctly
resolved `task76-trial3` and `task55-trial0`, two unrelated traces needing
the identical multi-call pattern, without any further code changes.

### What the 35 labels found

| Category | Count | Sentinel has a detector? |
|---|---|---|
| `missing_tool` | 10 | yes (the tool count, at least, is checkable) |
| `wrong_tool_argument` | 9 | no |
| `grading_artifact` | 6 | n/a — agent behavior was defensible |
| `ordering_error` | 4 | no |
| `fabricated_info` | 3 | no |
| `missing_confirmation` | 2 | no |
| `wrong_tool` | 1 | no |

Two findings dominate the writeup-worthy material:

**A dominant behavioral pattern, not a category.** 18 of 35 traces — more
than half — share one underlying shape regardless of which specific category
they got labeled: the agent stops a required search or workflow the moment
it finds one plausible answer, instead of finishing the search the request
actually needed. It shows up as a declined double-check, a false claim that
unexamined orders are "already cancelled," a wrong entity match, an
unresolved comparative constraint, and a straight refusal to proceed without
information the agent already had the tools to find itself. Two independent
trials of `task98` failed in the *identical* way — same wrong tool attempt,
same sequencing mistake, same escalation wording, nearly word for word —
which is evidence of a systematic tendency in GPT-4o for this scenario, not
one unlucky rollout.

**Four passing traces had real problems tau-bench's own reward missed
entirely.** This is the headline finding of the whole day, ranked above any
category count. `task40-trial0`: the agent promised a nonexistent
split-payment option, obtained confirmation for it, and then falsely told
the customer her gift card had been applied when it hadn't — `reward=1.0`.
`task108-trial0`: a real but minor undisclosed $3.10 charge before an
irreversible modification — `reward=1.0`. `task13-trial2`: an explicit false
statement ("you can receive the refund via PayPal") that gets caught by the
tool itself and self-corrects to an accurate final report — `reward=1.0`.
`task3-trial3`: the customer explicitly says "yes, please proceed," and
**nothing happens** — the conversation just ends — `reward=1.0` anyway. Its
sibling trial, `task3-trial1`, executes an irreversible modification on the
*wrong* item entirely, for the same underlying task — also `reward=1.0`.
Checked directly: both `task3` trials pass because tau-bench's grading for
this task is a bare substring check for `"10"`, which is satisfied by
digits embedded incidentally in unrelated product IDs returned by tool
calls, not by anything the agent correctly says or does. That specific
task's grading checks close to nothing.

### Building the adapter

One constraint overrode every other design choice: `Step.index` had to equal
a message's exact position in tau-bench's raw trajectory, because all 35
labels reference specific tau-bench step numbers. Get this wrong and a full
day of verified labeling becomes unscoreable.

`expected_tools` is populated from tau-bench's own graded actions, filtered
to a whitelist of consequential (state-mutating) tool names, with duplicates
preserved so a tool required twice registers as needed twice. Read-only
calls are deliberately excluded — including them would flag ordinary
variation in *how* an agent gathers information as a missing required
action, exactly the false-positive shape rejected during labeling itself
(see `task32`, `task33-trial0` notes). `forbidden_tools` is left empty;
inferring "this tool is wrong given this order's status" needs
cross-referencing arguments against retrieved state, which this adapter
doesn't attempt. `context_overflow` cannot apply at all — tau-bench reports
no token counts. Both are documented gaps, not oversights.

### What adapter testing found before any scoring happened

Running Sentinel on a single known trace (`task22-trial2`, the Rule 5
worked example) confirmed the mechanics: category came back `missing_tool`,
correct. The root step index did not match (Sentinel: 2, label: 14) — and
checking why surfaced a real, distinct architectural gap: `detect_missing_tool`
anchors to "the plan step if present, else first assistant step," and
tau-bench conversations have no `PLAN` step type at all, so it falls back to
the first assistant message in the entire trace, a far cruder signal than
the reasoning Rules 1–7 apply. This is a limitation of the *anchor logic*,
not the missing_tool detection itself, which localizes the right cause.

A second, more consequential discovery: `ignored_tool_error` fires on *any*
tool error not explicitly restated in the final answer, including entirely
routine, successful retries — an email lookup failing, correctly falling
back to name-plus-zip, with the task completing fine. It has no concept of
recovery, exactly the distinction Rule 6 had to be written into this
project's own labeling process to capture. Sentinel's real detector hasn't
learned the rule its own evaluator needed.

### Full results

**Coverage, all 182 failing traces:** Sentinel produced a finding on 163
(89.6%), stayed silent on 19 (10.4%). Coverage was never the weak point.

**Precision, all 274 passing traces with no known issue** (4 excluded, see
above — flagging them is a correct catch, not a false positive):

| | |
|---|---|
| False positives | 185–186 / 274 |
| Precision, as measured | 32.1–32.5% |
| — from `ignored_tool_error` | 81 |
| — from `fabricated_specifics` | 80 |
| — from `missing_tool` (overgeneralizing) | 24 |
| **Precision if the top two were fixed** | **90.9%** |

Two detectors account for 87% of every false positive. This is not a diffuse
problem across seven detectors — it's concentrated, identified, and
fixable. `fabricated_specifics`'s exact mechanism (a real, likely computed
value like `$16.63` gets flagged as ungrounded) is not fully root-caused yet
and is stated here as an open question, not a diagnosed bug the way
`ignored_tool_error`'s is.

**Scored directly against the 35 hand-labels**, split by whether a real
agent fault exists (29 traces) or the agent's behavior was defensible (6
`grading_artifact` traces):

| | |
|---|---|
| Category match, traces labeled `has_detector=True` | **10 / 10 (100%)** |
| Category match, traces labeled `has_detector=False` | **0 / 19 (0%)** |
| Step index match, even where category matched | 0 / 10 |
| No-fault traces correctly left `HEALTHY` | 2 / 6 |
| No-fault traces incorrectly flagged | 4 / 6 (same two detectors) |

The 100/0 split is worth sitting with. Every trace independently judged
during labeling to be within Sentinel's real capability was diagnosed
correctly. Every trace judged to be outside it was not. That kind of exact
correlation is strong evidence the `has_detector` calls made throughout
labeling reflected real technical understanding of the codebase, not
guesses reconciled after the fact.

### Independently reproduced

The batch scoring script was handed off and rerun independently, on a
different machine, with a live `ANTHROPIC_API_KEY` configured (this
project's own, from Day 3). Result: 185 false positives against my 186 —
a one-trace difference, fully explained rather than shrugged off.
`task27-trial1` was a Tier 2 candidate my keyless sandbox run left
unconfirmed; with Tier 3 live, the judge correctly read the actual
conversation (an agent honestly reporting an error to the customer, not
contradicting it) and suppressed the false positive Tier 2 alone couldn't
resolve. Checked directly against the transcript: Tier 3's call was right.
Every other number, coverage, the two dominant false-positive categories,
their counts, matched exactly across two independent machines.

### What Day 4 has and hasn't proven

**Measured:** a real detector bug, found and fixed with no regression.
Thirty-five traces of real GPT-4o behavior, blind-labeled against a rubric
that itself evolved under real evidence. 89.6% coverage. 32–33% precision as
currently calibrated, concentrated in two identifiable detectors, rising to
91% projected if those two are fixed. A 100%/0% split validating that the
labeling judgment about Sentinel's own capability was accurate. Four
passing-graded traces with real, verified problems the benchmark's own
reward could not see, including two sibling trials of one task where the
entire grading mechanism turned out to be close to meaningless.

**Not measured:** whether coverage holds on a fully random (non-stratified)
sample. Whether `ignored_tool_error`'s and `fabricated_specifics`' false
positive rates generalize past retail into other tau-bench domains. Whether
fixing the two dominant detectors actually delivers the 90.9% projection, or
whether fixing them introduces new false negatives elsewhere — that number
is a target computed from today's data, not a measured result from a
rebuilt detector. `context_overflow` and `wrong_tool` (via `forbidden_tools`
inference) remain entirely untestable against this dataset by construction.

**Next, and explicitly not squeezed into today:** real detector work for
the two miscalibrated existing detectors, and new detector design for the
four capability gaps this sample surfaced — grounded-value-wrong-entity,
sequencing/state-dependency, entity resolution across multiple candidates,
and incomplete-but-otherwise-correct tool arguments. That's legitimate scope
for whatever comes after this is written up, not something to context-switch
into mid-measurement.

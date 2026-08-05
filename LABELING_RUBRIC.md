# Labeling Rubric — τ-bench Trajectories

*For Day 4: measuring Sentinel against agent failures it didn't author.*

## Why this document exists

Sentinel's benchmark so far uses traces I wrote and labeled. τ-bench gives me
1,000+ real failures graded by someone else. But the *reward* only says
whether a trajectory failed — not where or why. Root-cause labels still
require human judgment, which means they can still be biased.

This rubric exists to constrain that judgment before it happens.

**The rule that has governed this project since Day 1 applies here without
exception: label the trace before running Sentinel on it. Never revise a
label after seeing the tool's output.** With synthetic traces I wrote, that
was a discipline. Here it's load-bearing — these traces are long and
genuinely ambiguous, and the pull to "well, Sentinel's answer is defensible
too" will be much stronger.

## Procedure

For each sampled trajectory:

1. **Read the system message first.** In τ-bench this is the domain policy —
   the rules the agent is required to follow. Most failures are policy
   violations, and you can't spot one without knowing the rule.
2. **Read `info.reward_info.actions`** — the ground-truth expected tool
   sequence, authored by Sierra. This is what *should* have happened.
3. **Read the message sequence in order.** Stop at the first step where the
   agent's behavior deviates from what a correct run would do.
4. **Record that step index and its category** using the taxonomy below.
5. **Then, and only then**, run Sentinel and record whether it agreed.

Budget ~5 minutes per trajectory. If you're past 10 minutes, label it `E1`
(see below) and move on — an honest "I couldn't determine this" is worth more
than a coin-flip label.

## Category taxonomy

Categories marked **[BLIND]** are ones Sentinel currently has no detector
for. They are included deliberately. If the taxonomy only contained things
Sentinel can catch, the coverage number would be meaningless.

### A — Decision-level (the agent chose wrong)

| Code | Category | Definition |
|---|---|---|
| A1 | `missing_tool` | A required tool from the expected sequence was never called |
| A2 | `wrong_tool` | Called a tool that shouldn't have been used for this task |
| A3 | `wrong_tool_argument` **[BLIND]** | Right tool, wrong arguments (wrong ID, wrong item, wrong payment method) |
| A4 | `ordering_error` **[BLIND]** | Correct tools, wrong sequence — e.g. acted before gathering required info |
| A5 | `premature_escalation` **[BLIND]** | Transferred to a human or gave up on a task that was solvable |
| A6 | `missing_confirmation` **[BLIND]** | Executed a consequential action without the policy-required user confirmation |

### B — Execution-level (the agent mishandled a result)

| Code | Category | Definition |
|---|---|---|
| B1 | `ignored_tool_error` | A tool returned an error; the agent proceeded as if it had succeeded |
| B2 | `tool_loop` | Same tool, same arguments, repeated past any useful point |
| B3 | `incomplete_execution` **[BLIND]** | Began a multi-step action and stopped partway (e.g. cancelled without confirming) |

### C — Communication-level (the final answer is wrong)

| Code | Category | Definition |
|---|---|---|
| C1 | `fabricated_info` | Final answer states specifics (IDs, amounts, statuses) present in no tool result |
| C2 | `policy_contradiction` | Final answer contradicts the system-message policy — *the Tier 2/3 case* |
| C3 | `false_success` **[BLIND]** | Agent claims the task is complete when the environment state says otherwise |

### D — Not the agent's fault

| Code | Category | Definition |
|---|---|---|
| D1 | `user_simulator_fault` | The simulated user gave contradictory or wrong information |
| D2 | `environment_fault` | Task spec, database, or tool behaved incorrectly |
| D3 | `grading_artifact` | `reward=0` but the agent's behavior looks defensible; the grader is arguably wrong |

**Category D is not an escape hatch — it's a real finding.** τ-bench's own
tooling assigns fault to *user, agent, or environment* precisely because
non-agent failures exist in this data. If a meaningful share of graded
failures aren't agent failures at all, that's worth reporting, and it caps
the accuracy any localizer can achieve on this dataset.

### E — Undetermined

| Code | Category | Definition |
|---|---|---|
| E1 | `unlabelable` | Genuinely can't determine the root cause within the time budget |

## Tie-breaking rules

**Rule 1 — Earliest deviation wins.** If multiple things went wrong, the root
is the first one. Later problems are propagation.

*Known bias, stated openly:* this is the same rule Sentinel's localizer uses.
Aligning the rubric with the tool's own definition of "root cause" will
inflate agreement relative to a rubric built on a different definition (e.g.
"most causally responsible step"). I'm using it anyway because it's the
definition the entire project is built on and changing it mid-measurement
would be worse — but the Day 4 writeup must disclose it. A reader should know
the measurement isn't fully independent of the thing being measured.

**Rule 2 — Decision beats symptom.** If a wrong tool choice at step 4 caused
a fabricated answer at step 12, label the decision (A2), not the symptom (C1).

**Rule 3 — Agent fault beats environment noise.** If the user simulator was
sloppy *but* the agent still had enough information to succeed, label the
agent (A–C), not D1.

**Rule 4 — When torn between two categories, pick the more specific one**, and
note the alternative in `notes`. Ambiguity you record is data; ambiguity you
silently resolve is bias.

**Rule 5 — Indexing omissions.** A wrong action has an obvious step index. A
*missing* action does not. For omission categories (A1, A5, B3), the root
step index is **the step where the agent moved on instead** — usually the
assistant message that concluded the exchange without making the required
call.

*Worked example (retail task 22, trial 2):* the agent authenticates, updates
the user's address at step 12, and announces success at step 14. It never
calls `get_order_details` or `modify_pending_order_address`, both of which
are in the expected sequence — pending orders still carry the old address.
The root step index is **14**, the message where the agent declared the task
complete instead of propagating the change. Category A1.

That trace also contains a second defect: at step 20 the agent "reverts" the
address using `address1="Denver"`, which is not the original street address.
That's A3 (`wrong_tool_argument`) — but it happens *later*, so under Rule 1 it
is propagation, not root. Record it in `alternative_considered`.

This is exactly the kind of case where Sentinel and a careful human can
reasonably disagree, and it should be labeled before Sentinel is ever run on it.

**Rule 6 — A stateless, self-corrected deviation doesn't outrank a deviation
with lasting consequence.** Rule 1 assumes deviations accumulate: the earliest
one sets the causal chain in motion. That assumption breaks when an earlier
deviation errors out cleanly, changes nothing about system state, and is
immediately followed by a correct self-recovery. A failed attempt with zero
trace left behind is closer to a discarded false start than a root cause. In
that specific situation, the root is the earliest deviation that actually
produces a lasting effect on the final outcome, not the earliest deviation of
any kind.

*Worked example (retail task 98, trial 0):* the agent calls
`exchange_delivered_order_items` on an order it already knows is pending
(step 20). The call errors immediately (`non-delivered order cannot be
exchanged`), changes nothing, and the very next planning step correctly
recognizes the order is pending and switches to `modify_pending_order_items`.
That correction succeeds — but running it before the required address change
flips the order's status to `pending (item modified)`, which makes the
address modification fail two steps later (`non-pending order cannot be
modified`). The root is the sequencing choice, not the earlier, harmless
wrong-tool attempt, because the wrong-tool attempt left nothing behind for
the later failure to depend on. Category A4 (`ordering_error`), rooted at the
sequencing step, not the earlier stateless one.

This is not a blanket license to ignore every recovered error. If a
"corrected" deviation turns out to have left a partial side effect, or the
recovery itself introduces a new problem, Rule 6 doesn't apply and Rule 1's
plain earliest-wins logic takes back over. When genuinely unsure whether a
deviation was truly stateless, fall back to Rule 4: pick the best fit, log
the alternative.

**Rule 7 — Root cause is the earliest deviation that closes off correction,
not the earliest sign of trouble.** An agent's first wrong guess is not
automatically the root if a real opportunity to correct it existed and was
offered. When the user or the environment gives the agent an explicit,
unambiguous chance to verify or reconsider, and the agent declines and
proceeds anyway, the root moves to that declined opportunity, not the
original guess. This is a more precise restatement of the principle this
whole project was built on: Sentinel's founding pitch was never "the first
anomaly," it was "the first *irreversible* mistake." Rule 7 makes that
explicit in the labeling process, not just the product description.

*Worked example (retail task 76, trial 3):* at step 16 the agent claims an
order doesn't contain a skateboard, having checked only 1 of the user's 6
orders. That alone is a recoverable, momentary error. At step 17 the user
explicitly pushes back: "I'm quite sure there's supposed to be a skateboard
in there... is it possible to double-check?" — a direct, unambiguous
invitation to verify. At step 18 the agent declines, repeats the same
unsupported conclusion, and pivots straight to offering cancellation
instead. That is the moment the error becomes locked in. Root step 18, not 16.

Rule 6 and Rule 7 pull in opposite directions and both matter: Rule 6
*demotes* an earlier deviation because it was stateless and self-corrected
with nothing depending on it. Rule 7 *promotes* a later moment because it's
where an offered correction was refused. Together they refine Rule 1's
"earliest deviation" into "earliest deviation that actually sticks."

## Label file format

Extends the existing `ground_truth.json` schema with fields this dataset makes
possible:

```json
{
  "taubench-retail-task5-trial0": {
    "root_category": "wrong_tool",
    "root_step_index": 4,
    "rubric_code": "A2",
    "fault_owner": "agent",
    "sentinel_has_detector": true,
    "labeler_confidence": "high",
    "notes": "Called find_user_id_by_email after zip lookup failed; expected sequence uses find_user_id_by_name_zip with corrected zip.",
    "alternative_considered": "A3 (wrong argument on the zip) — rejected because the agent switched tools rather than retrying with the right zip."
  }
}
```

- `sentinel_has_detector` — set **at labeling time**, from the [BLIND] markers
  above, *not* from what Sentinel actually outputs. This is what separates
  "Sentinel missed something it should have caught" from "Sentinel has no
  detector for this class at all." Two very different findings.
- `labeler_confidence` — `high` / `medium` / `low`. Report accuracy on
  high-confidence labels separately; if the tool only does well on the easy
  ones, that should be visible.

## Sampling plan

Stratify, don't take the first N — the file is ordered by task ID, and
consecutive entries are near-duplicates of the same task.

| Stratum | Target n | Why |
|---|---|---|
| Unexpected tool called (46% of failures) | 10 | Largest bucket; Sentinel's `wrong_tool` should do well |
| Missing expected tool (6%) | 5 | Small bucket, but the canonical Sentinel case |
| Both missing and unexpected (37%) | 5 | Multi-fault — tests the earliest-deviation rule |
| **Correct tool set, failed anyway (11%)** | 10 | **The hard ones.** Expect most [BLIND] categories here |
| Passing trajectories (`reward=1`) | 5 | False-positive check with a known-good answer |

Total ~35. The last stratum matters: five trajectories that *passed* should
produce zero findings. Any finding there is a false positive you can verify
without labeling anything.

## What gets reported

Three numbers, computed separately, never averaged into one:

1. **Precision** — false-positive rate across all 278 passing trajectories (no labeling required)
2. **Coverage** — of 182 graded failures, how often Sentinel produces any finding (no labeling required)
3. **Localization accuracy** — on the ~30 hand-labeled failures, split by whether a detector exists for that category

And one qualitative finding: **the distribution of rubric codes**. If most
real failures land in [BLIND] categories, that's the most useful output of
Day 4 regardless of what the accuracy numbers say — it tells you what to
build next, and it's a genuinely publishable result even if the tool performs
badly.
